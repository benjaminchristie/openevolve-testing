#include "common.hpp"
#include <cmath>

/**
@evolve(linalg)
*/
double dot_product(const double* a, const double* b, int n) {
    double sum = 0.0;
    for (int i = 0; i < n; ++i) {
        sum += a[i] * b[i];
    }
    return sum;
}

/**
@evolve(linalg)
*/
double vector_norm(const double* v, int n) {
    return std::sqrt(dot_product(v, v, n));
}
