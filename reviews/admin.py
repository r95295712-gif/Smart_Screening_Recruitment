from django.contrib import admin

from .models import PositionReviewer, ReviewBatch, Reviewer, ReviewItem

admin.site.register([Reviewer, PositionReviewer, ReviewBatch, ReviewItem])
