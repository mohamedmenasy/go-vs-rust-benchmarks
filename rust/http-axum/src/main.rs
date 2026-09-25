//! Baseline Rust HTTP server: Axum 0.8 on hyper + Tokio (multi-threaded
//! runtime, worker count from TOKIO_WORKER_THREADS). Mirrors go/http.
//!
//!   GET /users/{id}  parse id, 1000 mixing rounds, build + JSON-encode a user
//!   GET /health      "ok"
//!
//! No logging, no middleware. Parity with Go's net/http: listen backlog =
//! somaxconn, TCP_NODELAY on every accepted connection, HTTP/1.1 keep-alive.

use std::net::SocketAddr;

use axum::extract::Path;
use axum::http::{StatusCode, header};
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use axum::serve::ListenerExt;
use axum::{Json, Router};
use tokio::net::TcpSocket;

async fn users(Path(id): Path<String>) -> Response {
    match http_common::build_user(&id) {
        Some(u) => Json(u).into_response(),
        None => {
            (StatusCode::BAD_REQUEST, [(header::CONTENT_TYPE, "application/json")], http_common::ERROR_BODY)
                .into_response()
        }
    }
}

async fn health() -> &'static str {
    "ok"
}

#[tokio::main]
async fn main() {
    let app = Router::new().route("/users/{id}", get(users)).route("/health", get(health));
    let addr: SocketAddr = http_common::addr().parse().expect("valid --addr");
    let socket = if addr.is_ipv4() { TcpSocket::new_v4() } else { TcpSocket::new_v6() }.expect("socket");
    socket.set_reuseaddr(true).expect("SO_REUSEADDR");
    socket.bind(addr).expect("bind");
    let listener = socket.listen(http_common::somaxconn()).expect("listen");
    let listener = listener.tap_io(|tcp| {
        let _ = tcp.set_nodelay(true);
    });
    eprintln!(
        "listening {addr} (axum, tokio workers={})",
        std::env::var("TOKIO_WORKER_THREADS").unwrap_or_else(|_| "default".into())
    );
    axum::serve(listener, app).await.expect("serve");
}
