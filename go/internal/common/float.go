package common

import "math"

// F64Bits returns the IEEE-754 bit pattern of f.
func F64Bits(f float64) uint64 { return math.Float64bits(f) }
