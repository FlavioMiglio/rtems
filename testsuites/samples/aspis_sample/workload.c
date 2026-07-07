/* workload.c — calcolo puro, nessuna dipendenza RTEMS.
 * Questo e' l'UNICO file che passa per ASPIS.
 * Matrice deterministica A[i][j] = i*N + j + 1; calcola B = A*A e
 * restituisce la somma di tutti gli elementi di B come checksum a 32 bit
 * (overflow wrap voluto -> valore riproducibile bit a bit, verificabile). */
#include <stdint.h>

#define N 16

uint32_t workload_run(void);

uint32_t workload_run(void)
{
    static uint32_t A[N][N];
    static uint32_t B[N][N];

    for (int i = 0; i < N; i++)
        for (int j = 0; j < N; j++)
            A[i][j] = (uint32_t)(i * N + j + 1);

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

    return checksum;
}
