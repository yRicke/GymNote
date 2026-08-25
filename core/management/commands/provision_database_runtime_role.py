import os

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from psycopg import sql


class Command(BaseCommand):
    help = "Provisiona o papel PostgreSQL de runtime sem BYPASSRLS."

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            raise CommandError("Este comando exige PostgreSQL.")

        role_name = os.environ.get("DATABASE_RUNTIME_ROLE", "gymnote_runtime")
        role_password = os.environ.get("DATABASE_RUNTIME_PASSWORD")
        if not role_password:
            raise CommandError("DATABASE_RUNTIME_PASSWORD é obrigatória.")

        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "SELECT rolcreaterole FROM pg_roles WHERE rolname = current_user"
            )
            can_create_role = cursor.fetchone()[0]
            if not can_create_role:
                raise CommandError("A conexão administrativa não pode gerenciar roles.")

            cursor.execute(
                """
                SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication,
                       rolbypassrls
                FROM pg_roles
                WHERE rolname = %s
                """,
                [role_name],
            )
            role_flags = cursor.fetchone()
            role_identifier = sql.Identifier(role_name)
            if role_flags is None:
                cursor.execute(
                    sql.SQL(
                        """
                        CREATE ROLE {} WITH LOGIN PASSWORD %s
                        NOSUPERUSER NOCREATEDB NOCREATEROLE
                        NOREPLICATION NOBYPASSRLS
                        """
                    ).format(role_identifier),
                    [role_password],
                )
            else:
                if any(role_flags):
                    raise CommandError(
                        "A role existente possui privilégios administrativos; "
                        "corrija-a com uma credencial de superusuário."
                    )
                cursor.execute(
                    sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD %s").format(
                        role_identifier
                    ),
                    [role_password],
                )

            database_identifier = sql.Identifier(connection.settings_dict["NAME"])
            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    database_identifier,
                    role_identifier,
                )
            )
            cursor.execute(
                sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(
                    role_identifier
                )
            )
            cursor.execute(
                sql.SQL(
                    """
                    GRANT SELECT, INSERT, UPDATE, DELETE
                    ON ALL TABLES IN SCHEMA public TO {}
                    """
                ).format(role_identifier)
            )
            cursor.execute(
                sql.SQL(
                    """
                    GRANT USAGE, SELECT
                    ON ALL SEQUENCES IN SCHEMA public TO {}
                    """
                ).format(role_identifier)
            )
            cursor.execute("SELECT current_user")
            owner_identifier = sql.Identifier(cursor.fetchone()[0])
            cursor.execute(
                sql.SQL(
                    """
                    ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public
                    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}
                    """
                ).format(owner_identifier, role_identifier)
            )
            cursor.execute(
                sql.SQL(
                    """
                    ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public
                    GRANT USAGE, SELECT ON SEQUENCES TO {}
                    """
                ).format(owner_identifier, role_identifier)
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Role {role_name} provisionada com NOBYPASSRLS e privilégios de runtime."
            )
        )
