from django.test import TestCase

from apps.accounts.models import User
from apps.products.models import OwnershipRecord, Product
from apps.products.serializers import OwnershipRecordPublicSerializer
from apps.products.services import TrustScoreService


class ProductVerificationTests(TestCase):
    def setUp(self):
        self.business = User.objects.create_user(
            phone_number='0500000001',
            user_type=User.BUSINESS,
            cr_submitted=True,
            business_name='Tawatur Store',
        )
        self.product = Product.objects.create(
            category=Product.SMARTPHONE,
            brand='Apple',
            model='iPhone',
            condition=Product.CONDITION_GOOD,
            registered_by=self.business,
        )
        self.record = OwnershipRecord.objects.create(
            product=self.product,
            owner=self.business,
            transfer_type=OwnershipRecord.INITIAL,
            is_current=True,
        )

    def test_business_submission_counts_toward_chain_integrity(self):
        self.assertEqual(self.product.chain_integrity, 100)

    def test_business_owner_is_marked_verified_in_public_history(self):
        data = OwnershipRecordPublicSerializer(self.record).data

        self.assertTrue(data['owner_verified'])

    def test_business_submission_counts_toward_trust_score(self):
        score, level = TrustScoreService.calculate(self.product)

        self.assertEqual(score, 70)
        self.assertEqual(level, Product.TRUST_HIGH)
