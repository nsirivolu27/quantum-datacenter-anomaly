# Observe the worker's actual eth0. No synthetic Zeek records are generated.
@load base/protocols/conn
@load base/protocols/http
@load base/protocols/dns
redef LogAscii::use_json = T;
redef Log::default_rotation_interval = 0secs;
redef tcp_attempt_delay = 3secs;
