// Rollups and retention on InfluxDB (cloud backend) - the counterpart of the SQLite
// backend's readings_hourly / readings_daily tables.
//
// 1. Buckets with retention (influx CLI):
//      influx bucket create -n power        -r 30d    # raw 1 Hz readings
//      influx bucket create -n power_hourly -r 400d   # hourly rollups
//      influx bucket create -n power_daily  -r 0      # daily rollups, kept forever
// 2. Register the two tasks below (influx task create -f <file>), one task per file.
//
// Late data: the tasks re-process a trailing window (offset/range below) on every run,
// so a meter that syncs a few hours of backlog after an outage still lands in the right
// rollups. Rows older than the window need a manual backfill run of the same query.

// ---------------------------------------------------------------- task 1: hourly
import "timezone"
option location = timezone.location(name: "Asia/Kolkata")
option task = {name: "voltix-hourly", every: 15m, offset: 1m}

data = from(bucket: "power")
    |> range(start: -26h)
    |> filter(fn: (r) => r._measurement == "power_data")

data |> filter(fn: (r) => r._field != "energy_kwh")
    |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
    |> set(key: "_measurement", value: "power_hourly")
    |> to(bucket: "power_hourly")

data |> filter(fn: (r) => r._field == "energy_kwh")
    |> difference(nonNegative: true)
    |> aggregateWindow(every: 1h, fn: sum, createEmpty: false)
    |> set(key: "_field", value: "consumed_kwh")
    |> set(key: "_measurement", value: "power_hourly")
    |> to(bucket: "power_hourly")

// ---------------------------------------------------------------- task 2: daily (separate file)
// import "timezone"
// option location = timezone.location(name: "Asia/Kolkata")
// option task = {name: "voltix-daily", every: 1h, offset: 5m}
//
// from(bucket: "power_hourly")
//     |> range(start: -3d)
//     |> filter(fn: (r) => r._measurement == "power_hourly")
//     |> aggregateWindow(every: 1d, fn: (column, tables=<-) =>
//            if column == "_value" then tables |> mean(column) else tables |> sum(column),
//            createEmpty: false)
//     |> set(key: "_measurement", value: "power_daily")
//     |> to(bucket: "power_daily")
