# Generated to repair missing file_size and mime_type columns on TransactionDocument.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("transactions", "0003_restore_transactiondocument_filename"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                """
                ALTER TABLE transactions_transactiondocument
                ADD COLUMN IF NOT EXISTS file_size integer;
                """,
                """
                ALTER TABLE transactions_transactiondocument
                ADD COLUMN IF NOT EXISTS mime_type varchar(100);
                """,
                """
                UPDATE transactions_transactiondocument
                SET file_size = COALESCE(file_size, 0)
                WHERE file_size IS NULL;
                """,
                """
                UPDATE transactions_transactiondocument
                SET mime_type = COALESCE(NULLIF(mime_type, ''), 'application/octet-stream')
                WHERE mime_type IS NULL OR mime_type = '';
                """,
                """
                ALTER TABLE transactions_transactiondocument
                ALTER COLUMN file_size SET DEFAULT 0;
                """,
                """
                ALTER TABLE transactions_transactiondocument
                ALTER COLUMN file_size SET NOT NULL;
                """,
                """
                ALTER TABLE transactions_transactiondocument
                ALTER COLUMN mime_type SET DEFAULT 'application/octet-stream';
                """,
                """
                ALTER TABLE transactions_transactiondocument
                ALTER COLUMN mime_type SET NOT NULL;
                """,
            ],
            reverse_sql=[
                """
                ALTER TABLE transactions_transactiondocument
                DROP COLUMN IF EXISTS file_size;
                """,
                """
                ALTER TABLE transactions_transactiondocument
                DROP COLUMN IF EXISTS mime_type;
                """
            ],
        ),
    ]
