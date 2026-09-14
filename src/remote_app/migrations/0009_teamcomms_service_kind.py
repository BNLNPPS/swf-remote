from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('remote_app', '0008_teamcomms_auth')]

    operations = [
        migrations.AddField(
            model_name='apitoken', name='teamcomms_service_kind',
            field=models.CharField(max_length=16, blank=True, default='',
                choices=[('', 'Account / AI client'), ('program', 'Program'), ('connector', 'Platform connector')]),
        ),
        migrations.AddConstraint(
            model_name='apitoken',
            constraint=models.CheckConstraint(
                condition=(models.Q(teamcomms_service_kind='') |
                           models.Q(teamcomms_service_kind__in=['program', 'connector'], teamcomms_ai=False)),
                name='api_token_teamcomms_kind'),
        ),
    ]
