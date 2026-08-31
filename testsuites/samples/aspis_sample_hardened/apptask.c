/* apptask.c */
#ifdef HAVE_CONFIG_H
#include "config.h"
#endif
#include "system.h"
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>

#define ASPIS_CHECKPOINT \
  __attribute__((annotate("exclude"), noinline, optnone))

uint32_t workload_run(void);
void aspis_test_injection_point(void) ASPIS_CHECKPOINT;
void aspis_data_checkpoint(uint32_t value) ASPIS_CHECKPOINT;

void aspis_test_injection_point(void)
{
}

void aspis_data_checkpoint(uint32_t value)
{
    (void) value;
}

rtems_task Application_task(rtems_task_argument argument)
{
    (void) argument;
    uint32_t r = workload_run();
    printf("checksum = 0x%08x\n", (unsigned)r);
    printf("done\n");
    exit(0);
}
