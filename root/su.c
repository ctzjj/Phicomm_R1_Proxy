/* tiny su: drop to nothing, become root, exec shell */
#include <unistd.h>
#include <stdlib.h>
int main(int argc, char **argv) {
    if (setgid(0) || setuid(0)) { perror("setuid"); return 1; }
    char *sh = "/system/bin/sh";
    char *av[2]; av[0] = "sh"; av[1] = NULL;
    char *env[] = {"PATH=/sbin:/system/sbin:/system/bin:/system/xbin", NULL};
    execve(sh, av, env);
    return 1;
}
