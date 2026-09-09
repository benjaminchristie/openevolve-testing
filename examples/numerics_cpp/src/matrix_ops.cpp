#include "common.hpp"

/**
@evolve(linalg)
*/
void matmul(const double* A, const double* B, double* C, int n) {
    for (int i = 0; i < n; ++i) {
        for (int j = 0; j < n; ++j) {
            double sum = 0.0;
            for (int k = 0; k < n; ++k) {
                sum += A[i * n + k] * B[k * n + j];
            }
            C[i * n + j] = sum;
        }
    }
}

/**
@evolve(linalg)
*/
void transpose(const double* A, double* T, int n) {
    for (int i = 0; i < n; ++i) {
        for (int j = 0; j < n; ++j) {
            T[j * n + i] = A[i * n + j];
        }
    }
}
