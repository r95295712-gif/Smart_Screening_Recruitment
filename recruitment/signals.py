from django.db.models.signals import post_save
from django.dispatch import receiver

from analysis.models import AnalysisItem
from reviews.models import ReviewItem
from talent_pool.models import TalentMembership

from .models import ResumeVersion


def mark_protected(resume):
    if resume and not resume.protected:
        ResumeVersion.objects.filter(pk=resume.pk).update(protected=True)
        resume.protected = True


@receiver(post_save, sender=AnalysisItem)
def protect_analyzed_resume(sender, instance, created, **kwargs):
    if created:
        mark_protected(instance.resume_version)


@receiver(post_save, sender=ReviewItem)
def protect_reviewed_resume(sender, instance, created, **kwargs):
    if created:
        mark_protected(instance.resume_version)


@receiver(post_save, sender=TalentMembership)
def protect_talent_resume(sender, instance, created, **kwargs):
    if created:
        mark_protected(instance.resume_version)
