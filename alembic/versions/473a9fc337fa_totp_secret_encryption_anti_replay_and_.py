"""totp secret encryption anti-replay and mfa hardening

Revision ID: 473a9fc337fa
Revises: 628bcf5fd887
Create Date: 2026-09-27 15:42:19.446337
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '473a9fc337fa'
down_revision: Union[str, Sequence[str], None] = '628bcf5fd887'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default nécessaire : NOT NULL sur une table qui peut déjà
    # avoir des lignes (des pending_token en cours au moment du déploiement).
    op.add_column(
        'mfa_pending_tokens', sa.Column('failed_attempts', sa.Integer(), nullable=False, server_default='0')
    )
    op.add_column('user_mfa_methods', sa.Column('last_totp_counter', sa.Integer(), nullable=True))

    # batch_alter_table, pas alter_column directement : SQLite ne
    # supporte aucun ALTER COLUMN ... TYPE, seul le mode "batch"
    # d'Alembic sait le simuler (recrée la table dessous) — fonctionne
    # aussi normalement sur Postgres, donc safe dans les deux cas.
    with op.batch_alter_table('user_mfa_methods') as batch_op:
        batch_op.alter_column(
            'secret', existing_type=sa.VARCHAR(length=64), type_=sa.String(length=255), existing_nullable=True
        )

    _encrypt_legacy_plaintext_secrets()


def _encrypt_legacy_plaintext_secrets() -> None:
    """Un secret TOTP créé avant cette version est encore en clair —
    chiffré ici, une fois, au passage de la migration. Un secret déjà
    chiffré se déchiffre sans erreur (on ne le retouche pas) ; un
    secret en clair échoue (ce n'est pas un jeton Fernet valide),
    c'est ce qui distingue les deux sans colonne de version dédiée."""
    from forge.security import crypto

    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, secret FROM user_mfa_methods WHERE method = 'totp' AND secret IS NOT NULL")
    ).fetchall()

    for row_id, secret in rows:
        try:
            crypto.decrypt_secret(secret)
        except crypto.DecryptionError:
            connection.execute(
                sa.text("UPDATE user_mfa_methods SET secret = :new WHERE id = :row_id"),
                {"new": crypto.encrypt_secret(secret), "row_id": row_id},
            )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('user_mfa_methods') as batch_op:
        batch_op.alter_column(
            'secret', existing_type=sa.String(length=255), type_=sa.VARCHAR(length=64), existing_nullable=True
        )

    op.drop_column('user_mfa_methods', 'last_totp_counter')
    op.drop_column('mfa_pending_tokens', 'failed_attempts')
