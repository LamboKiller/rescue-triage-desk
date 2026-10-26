"""Volunteer boat intake: offers become pending assets that a human must verify before F1FLEET can dispatch them."""
from app.volunteers.detect import classify, is_offer
from app.volunteers.service import VolunteerService, PENDING, VERIFIED, REJECTED

__all__ = ['classify', 'is_offer', 'VolunteerService', 'PENDING', 'VERIFIED', 'REJECTED']
