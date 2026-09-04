from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('remote_app', '0006_rename_days_window'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ApiToken',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('label', models.CharField(blank=True, default='', max_length=100)),
                ('prefix', models.CharField(db_index=True, max_length=12)),
                ('key_hash', models.CharField(max_length=64, unique=True)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('last_used', models.DateTimeField(blank=True, null=True)),
                ('revoked', models.DateTimeField(blank=True, null=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='api_tokens', to=settings.AUTH_USER_MODEL)),
            ],
            options={'db_table': 'api_token'},
        ),
    ]
