class PostgresqlCommands:
    """Postgresql db commands class"""

    find_table = """
                    SELECT EXISTS (
                       SELECT FROM information_schema.tables 
                       WHERE  table_schema = 'public'
                       AND    table_name   = $1
                       );
                """
    config_names = """
                    SELECT name, value FROM config
                """
    create_config = """
                        CREATE TABLE config (
                            name TEXT NOT NULL,
                            value TEXT,
                            PRIMARY KEY (name)
                        );
                    """
    insert_into_config = """
                    INSERT INTO config (name, value) VALUES($1, $2)
                """
    create_profiles = """
                        CREATE TABLE profiles (
                            id BIGSERIAL,
                            name TEXT NOT NULL,
                            reference TEXT NULL,
                            profile_key BYTEA NULL,
                            PRIMARY KEY (id)
                        );
                        CREATE UNIQUE INDEX ix_profile_name ON profiles (name);
                    """
    insert_into_profiles = """
                    INSERT INTO profiles (name, profile_key) VALUES($1, $2)
                    ON CONFLICT DO NOTHING RETURNING id
                """
    create_items = """
                        ALTER TABLE items RENAME TO items_old;
                        CREATE TABLE items (
                            id BIGSERIAL,
                            profile_id BIGINT NOT NULL,
                            kind SMALLINT NOT NULL,
                            category BYTEA NOT NULL,
                            name BYTEA NOT NULL,
                            value BYTEA NOT NULL,
                            expiry TIMESTAMP NULL,
                            PRIMARY KEY(id),
                            FOREIGN KEY (profile_id) REFERENCES profiles (id)
                                ON DELETE CASCADE ON UPDATE CASCADE
                        );
                        CREATE UNIQUE INDEX ix_items_uniq ON items
                            (profile_id, kind, category, name);
                    """
    create_items_tags = """
                        CREATE TABLE items_tags (
                            id BIGSERIAL,
                            item_id BIGINT NOT NULL,
                            name BYTEA NOT NULL,
                            value BYTEA NOT NULL,
                            plaintext SMALLINT NOT NULL,
                            PRIMARY KEY (id),
                            FOREIGN KEY (item_id) REFERENCES items (id)
                                ON DELETE CASCADE ON UPDATE CASCADE
                        );
                        CREATE INDEX ix_items_tags_item_id ON items_tags(item_id);
                        CREATE INDEX ix_items_tags_name_enc ON items_tags(name, SUBSTR(value, 1, 12)) include (item_id) WHERE plaintext=0;
                        CREATE INDEX ix_items_tags_name_plain ON items_tags(name, value) include (item_id) WHERE plaintext=1;
                    """
    drop_tables = """
            BEGIN TRANSACTION;
            DROP TABLE items_old CASCADE;
            DROP TABLE metadata;
            DROP TABLE tags_encrypted;
            DROP TABLE tags_plaintext;
            INSERT INTO config (name, value) VALUES ('version', 1);
            COMMIT;
        """
    pending_items = """
            SELECT i.id, i.type, i.name, i.value, i.key,
            (SELECT string_agg(encode(te.name::bytea, 'hex') || ':' || encode(te.value::bytea, 'hex')::text, ',')
                FROM tags_encrypted te WHERE te.item_id = i.id) AS tags_enc,
            (SELECT string_agg(encode(tp.name::bytea, 'hex') || ':' || encode(tp.value::bytea, 'hex')::text, ',')
                FROM tags_plaintext tp WHERE tp.item_id = i.id) AS tags_plain
            FROM items_old i LIMIT $1;
            """
    pending_items_by_wallet_id = """
            SELECT i.wallet_id, i.id, i.type, i.name, i.value, i.key,
            (SELECT string_agg(encode(te.name::bytea, 'hex') || ':' || encode(te.value::bytea, 'hex')::text, ',')
                FROM tags_encrypted te WHERE te.item_id = i.id) AS tags_enc,
            (SELECT string_agg(encode(tp.name::bytea, 'hex') || ':' || encode(tp.value::bytea, 'hex')::text, ',')
                FROM tags_plaintext tp WHERE tp.item_id = i.id) AS tags_plain
            FROM items_old i WHERE i.wallet_id = $2 LIMIT $1;
            """
    insert_into_items = """
                        INSERT INTO items (profile_id, kind, category, name, value)
                        VALUES (1, 2, $1, $2, $3) RETURNING id
                    """
    insert_into_items_tags = """
                            INSERT INTO items_tags (item_id, plaintext, name, value)
                            VALUES ($1, $2, $3, $4)
                        """
    delete_item_in_items_old = "DELETE FROM items_old WHERE id IN ($1)"
