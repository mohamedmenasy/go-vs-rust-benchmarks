-- wrk / wrk2 script: deterministic request stream + machine-readable report.
--
-- Every thread cycles through GET /users/1 .. /users/10000, starting at a
-- thread-specific offset, so Go and Rust servers receive the same request mix.
-- done() prints one line "WRK_JSON {...}" with totals, error counts and the
-- latency distribution (microseconds). wrk2 records latency with coordinated-
-- omission correction; wrk does not.

local threads = {}
local counter = 0
local ids = 10000

function setup(thread)
  thread:set("offset", #threads * 1237)
  table.insert(threads, thread)
end

function init(args)
  counter = offset or 0
end

function request()
  counter = counter + 1
  return wrk.format("GET", "/users/" .. ((counter % ids) + 1))
end

function done(summary, latency, requests)
  local pct = {}
  for _, p in ipairs({ 50, 75, 90, 95, 99, 99.9, 99.99 }) do
    pct[#pct + 1] = string.format('"%s":%d', tostring(p), latency:percentile(p))
  end
  local e = summary.errors
  io.write(string.format(
    'WRK_JSON {"duration_us":%d,"requests":%d,"bytes":%d,' ..
    '"errors":{"connect":%d,"read":%d,"write":%d,"status":%d,"timeout":%d},' ..
    '"latency_us":{"min":%d,"max":%d,"mean":%.3f,"stdev":%.3f,"percentiles":{%s}}}\n',
    summary.duration, summary.requests, summary.bytes,
    e.connect, e.read, e.write, e.status, e.timeout,
    latency.min, latency.max, latency.mean, latency.stdev, table.concat(pct, ",")))
end
