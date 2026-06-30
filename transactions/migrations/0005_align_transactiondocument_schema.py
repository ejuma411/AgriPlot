# Generated to align TransactionDocument with the current model after schema drift.

from django.conf import settings
from django.db import migrations


def forwards(apps, schema_editor):
    TransactionDocument = apps.get_model("transactions", "TransactionDocument")
    Transaction = apps.get_model("transactions", "Transaction")
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))

    doc_table = schema_editor.quote_name(TransactionDocument._meta.db_table)
    tx_table = schema_editor.quote_name(Transaction._meta.db_table)
    user_table = schema_editor.quote_name(User._meta.db_table)

    with schema_editor.connection.cursor() as cursor:
        # Restore missing metadata columns.
        cursor.execute(f"ALTER TABLE {doc_table} ADD COLUMN IF NOT EXISTS document_date date;")
        cursor.execute(
            f"ALTER TABLE {doc_table} ADD COLUMN IF NOT EXISTS reference_number varchar(100) NOT NULL DEFAULT '';"
        )
        cursor.execute(f"ALTER TABLE {doc_table} ADD COLUMN IF NOT EXISTS search_date date;")
        cursor.execute(f"ALTER TABLE {doc_table} ADD COLUMN IF NOT EXISTS verified_by_id bigint;")
        cursor.execute(
            f"ALTER TABLE {doc_table} ADD COLUMN IF NOT EXISTS rejection_reason text NOT NULL DEFAULT '';"
        )
        cursor.execute(f"ALTER TABLE {doc_table} ADD COLUMN IF NOT EXISTS uploaded_by_id bigint;")
        cursor.execute(f"ALTER TABLE {doc_table} ADD COLUMN IF NOT EXISTS notes text NOT NULL DEFAULT '';")

        # Convert the legacy boolean status into the current text choices field.
        cursor.execute(
            f"""
            SELECT data_type
            FROM information_schema.columns
            WHERE table_name = %s
              AND column_name = 'status'
            """,
            [TransactionDocument._meta.db_table],
        )
        status_column = cursor.fetchone()
        if status_column and status_column[0] == "boolean":
            cursor.execute(f"ALTER TABLE {doc_table} ALTER COLUMN status DROP DEFAULT;")
            cursor.execute(
                f"""
                ALTER TABLE {doc_table}
                ALTER COLUMN status TYPE varchar(20)
                USING CASE WHEN status THEN 'verified' ELSE 'pending' END;
                """
            )
            cursor.execute(f"ALTER TABLE {doc_table} ALTER COLUMN status SET DEFAULT 'pending';")

        # Backfill uploaded_by from the transaction creator, then fall back to the buyer.
        cursor.execute(
            f"""
            UPDATE {doc_table} AS doc
            SET uploaded_by_id = COALESCE(tx.created_by_id, tx.buyer_id)
            FROM {tx_table} AS tx
            WHERE doc.transaction_id = tx.id
              AND doc.uploaded_by_id IS NULL;
            """
        )

        # If a verified document still lacks a verified_by user, use the uploader as a safe fallback.
        cursor.execute(
            f"""
            UPDATE {doc_table}
            SET verified_by_id = uploaded_by_id
            WHERE verified_by_id IS NULL
              AND status = 'verified'
              AND uploaded_by_id IS NOT NULL;
            """
        )

        cursor.execute(
            f"""
            ALTER TABLE {doc_table}
            ADD CONSTRAINT transactions_transactiondocument_verified_by_id_fk
            FOREIGN KEY (verified_by_id)
            REFERENCES {user_table} (id)
            DEFERRABLE INITIALLY DEFERRED;
            """
        )
        cursor.execute(
            f"""
            ALTER TABLE {doc_table}
            ADD CONSTRAINT transactions_transactiondocument_uploaded_by_id_fk
            FOREIGN KEY (uploaded_by_id)
            REFERENCES {user_table} (id)
            DEFERRABLE INITIALLY DEFERRED;
            """
        )

        cursor.execute(f"ALTER TABLE {doc_table} ALTER COLUMN uploaded_by_id SET NOT NULL;")
        cursor.execute(f"ALTER TABLE {doc_table} ALTER COLUMN reference_number SET DEFAULT '';")
        cursor.execute(f"ALTER TABLE {doc_table} ALTER COLUMN rejection_reason SET DEFAULT '';")
        cursor.execute(f"ALTER TABLE {doc_table} ALTER COLUMN notes SET DEFAULT '';")


def backwards(apps, schema_editor):
    TransactionDocument = apps.get_model("transactions", "TransactionDocument")

    doc_table = schema_editor.quote_name(TransactionDocument._meta.db_table)

    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            f"ALTER TABLE {doc_table} DROP CONSTRAINT IF EXISTS transactions_transactiondocument_uploaded_by_id_fk;"
        )
        cursor.execute(
            f"ALTER TABLE {doc_table} DROP CONSTRAINT IF EXISTS transactions_transactiondocument_verified_by_id_fk;"
        )
        cursor.execute(f"ALTER TABLE {doc_table} DROP COLUMN IF EXISTS notes;")
        cursor.execute(f"ALTER TABLE {doc_table} DROP COLUMN IF EXISTS uploaded_by_id;")
        cursor.execute(f"ALTER TABLE {doc_table} DROP COLUMN IF EXISTS rejection_reason;")
        cursor.execute(f"ALTER TABLE {doc_table} DROP COLUMN IF EXISTS verified_by_id;")
        cursor.execute(f"ALTER TABLE {doc_table} DROP COLUMN IF EXISTS search_date;")
        cursor.execute(f"ALTER TABLE {doc_table} DROP COLUMN IF EXISTS reference_number;")
        cursor.execute(f"ALTER TABLE {doc_table} DROP COLUMN IF EXISTS document_date;")
        cursor.execute(
            f"""
            ALTER TABLE {doc_table}
            ALTER COLUMN status TYPE boolean
            USING CASE WHEN status = 'verified' THEN TRUE ELSE FALSE END;
            """
        )


class Migration(migrations.Migration):

    dependencies = [
        ("transactions", "0004_restore_transactiondocument_file_size_mime_type"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
