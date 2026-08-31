#include <stdint.h>

#define N 16

uint32_t workload_run(void);
void aspis_test_injection_point(void);
void aspis_data_checkpoint(uint32_t value);

uint32_t workload_run(void)
{
    static uint32_t A[N][N];
    static uint32_t B[N][N];

    for (int i = 0; i < N; i++)
        for (int j = 0; j < N; j++)
            A[i][j] = (uint32_t)(i * N + j + 1);

    aspis_test_injection_point();

    for (int i = 0; i < N; i++)
        for (int j = 0; j < N; j++) {
            uint32_t acc = 0;
            for (int k = 0; k < N; k++)
                acc += A[i][k] * A[k][j];
            B[i][j] = acc;
        }

    uint32_t checksum = 0;
    for (int i = 0; i < N; i++)
        for (int j = 0; j < N; j++)
            checksum += B[i][j];

    aspis_data_checkpoint(checksum);

    return checksum;
}
