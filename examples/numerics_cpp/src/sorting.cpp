#include "common.hpp"
#include <utility>

/**
@evolve(sorting)
*/
void quicksort(int* arr, int lo, int hi) {
    if (lo >= hi) return;
    int pivot = arr[hi];
    int i = lo - 1;
    for (int j = lo; j < hi; ++j) {
        if (arr[j] < pivot) {
            ++i;
            std::swap(arr[i], arr[j]);
        }
    }
    std::swap(arr[i + 1], arr[hi]);
    int p = i + 1;
    quicksort(arr, lo, p - 1);
    quicksort(arr, p + 1, hi);
}
