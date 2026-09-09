#pragma once

double dot_product(const double* a, const double* b, int n);
double vector_norm(const double* v, int n);

void matmul(const double* A, const double* B, double* C, int n);
void transpose(const double* A, double* T, int n);

void quicksort(int* arr, int lo, int hi);
int binary_search(const int* arr, int n, int target);
