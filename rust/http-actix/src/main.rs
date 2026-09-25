//! Secondary Rust HTTP server: Actix Web 4 (one single-threaded runtime per
//! worker, workers = $BENCH_THREADS). Idiomatic handlers: `web::Path` and
//! `HttpResponse::json`. Mirrors go/http-gin. Backlog = somaxconn and
//! TCP_NODELAY on, as in the other servers; no logging middleware.

use actix_web::{App, HttpResponse, HttpServer, web};

async fn users(id: web::Path<String>) -> HttpResponse {
    match http_common::build_user(&id) {
        Some(u) => HttpResponse::Ok().json(u),
        None => HttpResponse::BadRequest().content_type("application/json").body(http_common::ERROR_BODY),
    }
}

async fn health() -> &'static str {
    "ok"
}

#[actix_web::main]
async fn main() -> std::io::Result<()> {
    let addr = http_common::addr();
    let workers = http_common::threads();
    eprintln!("listening {addr} (actix-web, workers={workers})");
    HttpServer::new(|| {
        App::new().route("/users/{id}", web::get().to(users)).route("/health", web::get().to(health))
    })
    .workers(workers)
    .backlog(http_common::somaxconn())
    .tcp_nodelay(true)
    .bind(addr)?
    .run()
    .await
}
