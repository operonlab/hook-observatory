module github.com/joneshong/hook-dispatcher

go 1.25.7

require (
	github.com/joneshong/workshop/libs/go-port-registry v0.0.0-00010101000000-000000000000
	github.com/redis/go-redis/v9 v9.18.0
	gopkg.in/yaml.v3 v3.0.1
)

require (
	github.com/cespare/xxhash/v2 v2.3.0 // indirect
	github.com/dgryski/go-rendezvous v0.0.0-20200823014737-9f7001d12a5f // indirect
	go.uber.org/atomic v1.11.0 // indirect
)

// Workshop monorepo: the port registry lives alongside hook-dispatcher.
replace github.com/joneshong/workshop/libs/go-port-registry => ../../libs/go-port-registry
