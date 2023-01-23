all: sqlite dbpw mwst mt-mwst

juggernaut:
	docker-compose build juggernaut-sqlite

alice.db bob.db &: | juggernaut
	docker-compose run juggernaut-sqlite
	docker cp alice-sqlite:/home/indy/.indy_client/wallet/alice/sqlite.db alice.db
	docker cp bob-sqlite:/home/indy/.indy_client/wallet/bob/sqlite.db bob.db
	docker-compose down -v

sqlite: alice.db bob.db

dbpw: | juggernaut
	docker-compose run juggernaut-dbpw
	docker cp db:/var/lib/postgresql/data dbpw
	docker-compose down -v

mwst: | juggernaut
	docker-compose run juggernaut-mwst
	docker cp db:/var/lib/postgresql/data mwst
	docker-compose down -v

mt-mwst: | juggernaut
	docker-compose run juggernaut-mt-mwst
	docker cp db:/var/lib/postgresql/data mt-mwst
	docker-compose down -v


.PHONY: sqlite juggernaut
