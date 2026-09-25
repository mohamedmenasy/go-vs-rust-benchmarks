// Command http-gin is the secondary Go HTTP server: Gin (on top of net/http)
// in release mode with no middleware (gin.New, not gin.Default, so there is
// no logger). Idiomatic Gin handlers: c.Param and c.JSON. Mirrors
// rust/http-actix.
package main

import (
	"fmt"
	"net"
	"net/http"
	"os"
	"runtime"

	"github.com/gin-gonic/gin"

	"github.com/mohamedmenasy/go-vs-rust-benchmarks/go/internal/api"
)

func main() {
	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.GET("/users/:id", func(c *gin.Context) {
		u, ok := api.BuildUser(c.Param("id"))
		if !ok {
			c.Data(http.StatusBadRequest, "application/json", api.ErrorBody)
			return
		}
		c.JSON(http.StatusOK, u)
	})
	r.GET("/health", func(c *gin.Context) { c.String(http.StatusOK, "ok") })
	addr := api.Addr(os.Args[1:])
	ln, err := net.Listen("tcp", addr)
	if err != nil {
		fmt.Fprintln(os.Stderr, "listen:", err)
		os.Exit(1)
	}
	fmt.Fprintf(os.Stderr, "listening %s (gin, GOMAXPROCS=%d)\n", ln.Addr(), runtime.GOMAXPROCS(0))
	if err := (&http.Server{Handler: r}).Serve(ln); err != nil {
		fmt.Fprintln(os.Stderr, "serve:", err)
		os.Exit(1)
	}
}
