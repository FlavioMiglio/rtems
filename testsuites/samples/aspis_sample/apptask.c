/* apptask.c */
#ifdef HAVE_CONFIG_H
#include "config.h"
#endif
#include "system.h"
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>

uint32_t workload_run(void);

rtems_task Application_task(rtems_task_argument argument)
{
    (void) argument;
    uint32_t r = workload_run();
    printf("checksum = 0x%08x\n", (unsigned)r);
    printf("done\n");
    exit(0);
}
