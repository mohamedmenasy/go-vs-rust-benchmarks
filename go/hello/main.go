// Command hello is the minimal CLI used for startup-time and binary-size
// measurements (mirror of rust/hello): idiomatic "print one line and exit".
package main

import "fmt"

// greeting is the constant the compile benchmark toggles for its
// one-file-change rebuild scenario.
const greeting = "hello"

func main() {
	fmt.Println(greeting)
}
