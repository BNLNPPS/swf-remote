from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('remote_app', '0007_apitoken'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='apitoken', name='teamcomms_ai',
            field=models.BooleanField(default=False),
        ),
        migrations.CreateModel(
            name='TeamCommsAuthReference',
            fields=[
                ('key_hash', models.CharField(max_length=64, primary_key=True, serialize=False)),
                ('session_key', models.CharField(max_length=40, blank=True, default='')),
                ('method', models.CharField(max_length=10)),
                ('path', models.TextField()),
                ('query_string', models.TextField(blank=True, default='')),
                ('body_sha256', models.CharField(max_length=64)),
                ('csrf_verified', models.BooleanField(default=False)),
                ('expires_at', models.DateTimeField(db_index=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
                ('token', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='remote_app.apitoken')),
            ],
            options={'db_table': 'teamcomms_auth_reference'},
        ),
    ]
