"""Alembic: applies the migrations to the database in MOCA_DATABASE_URL."""

from alembic import context

from webapp.db import Base, engine

with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata,
                      render_as_batch=connection.dialect.name == "sqlite")
    with context.begin_transaction():
        context.run_migrations()
    connection.commit()
