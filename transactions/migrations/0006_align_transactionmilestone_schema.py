# Generated to align TransactionMilestone with the current model after schema drift.

from django.conf import settings
from django.db import migrations


def forwards(apps, schema_editor):
    TransactionMilestone = apps.get_model("transactions", "TransactionMilestone")
    Transaction = apps.get_model("transactions", "Transaction")
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))

    milestone_table = schema_editor.quote_name(TransactionMilestone._meta.db_table)
    tx_table = schema_editor.quote_name(Transaction._meta.db_table)
    user_table = schema_editor.quote_name(User._meta.db_table)

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = %s
            """,
            [TransactionMilestone._meta.db_table],
        )
        existing_columns = {row[0] for row in cursor.fetchall()}

        cursor.execute(
            f"ALTER TABLE {milestone_table} ADD COLUMN IF NOT EXISTS milestone_type varchar(30);"
        )
        cursor.execute(
            f"ALTER TABLE {milestone_table} ADD COLUMN IF NOT EXISTS achieved_by_id bigint;"
        )
        cursor.execute(
            f"ALTER TABLE {milestone_table} ADD COLUMN IF NOT EXISTS achieved_at timestamp with time zone;"
        )
        cursor.execute(
            f"ALTER TABLE {milestone_table} ADD COLUMN IF NOT EXISTS notes text NOT NULL DEFAULT '';"
        )

        # Try to preserve historical rows when the old schema used a different column name.
        fallback_parts = ["NULLIF(milestone_type, '')"]
        if "stage" in existing_columns:
            fallback_parts.append("NULLIF(stage, '')")
        fallback_parts.append("'completed'")
        fallback_sql = ", ".join(fallback_parts)
        cursor.execute(
            f"""
            UPDATE {milestone_table}
            SET milestone_type = COALESCE({fallback_sql})
            WHERE milestone_type IS NULL OR milestone_type = '';
            """
        )

        # Make sure every row has a sensible achieved_at value.
        cursor.execute(
            f"""
            UPDATE {milestone_table}
            SET achieved_at = COALESCE(achieved_at, NOW())
            WHERE achieved_at IS NULL;
            """
        )

        # Backfill achieved_by from the related transaction creator, then buyer.
        cursor.execute(
            f"""
            UPDATE {milestone_table} AS ms
            SET achieved_by_id = COALESCE(tx.created_by_id, tx.buyer_id)
            FROM {tx_table} AS tx
            WHERE ms.transaction_id = tx.id
              AND ms.achieved_by_id IS NULL;
            """
        )

        # Keep the column constraints aligned with the model.
        cursor.execute(f"ALTER TABLE {milestone_table} ALTER COLUMN milestone_type SET NOT NULL;")
        cursor.execute(f"ALTER TABLE {milestone_table} ALTER COLUMN achieved_at SET NOT NULL;")
        cursor.execute(
            f"""
            ALTER TABLE {milestone_table}
            ADD CONSTRAINT transactions_transactionmilestone_achieved_by_id_fk
            FOREIGN KEY (achieved_by_id)
            REFERENCES {user_table} (id)
            DEFERRABLE INITIALLY DEFERRED;
            """
        )
        cursor.execute(
            f"""
            ALTER TABLE {milestone_table}
            ALTER COLUMN achieved_by_id DROP DEFAULT;
            """
        )


def backwards(apps, schema_editor):
    TransactionMilestone = apps.get_model("transactions", "TransactionMilestone")

    milestone_table = schema_editor.quote_name(TransactionMilestone._meta.db_table)

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            f"ALTER TABLE {milestone_table} DROP CONSTRAINT IF EXISTS transactions_transactionmilestone_achieved_by_id_fk;"
        )
        cursor.execute(f"ALTER TABLE {milestone_table} DROP COLUMN IF EXISTS notes;")
        cursor.execute(f"ALTER TABLE {milestone_table} DROP COLUMN IF EXISTS achieved_at;")
        cursor.execute(f"ALTER TABLE {milestone_table} DROP COLUMN IF EXISTS achieved_by_id;")
        cursor.execute(f"ALTER TABLE {milestone_table} DROP COLUMN IF EXISTS milestone_type;")


class Migration(migrations.Migration):

    dependencies = [
        ("transactions", "0005_align_transactiondocument_schema"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
