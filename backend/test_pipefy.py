import asyncio
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

class Lead:
    def __init__(self, name, email, company, need, interest_confirmed=False, meeting_link=None, meeting_datetime=None):
        self.name = name
        self.email = email
        self.company = company
        self.need = need
        self.interest_confirmed = interest_confirmed
        self.meeting_link = meeting_link
        self.meeting_datetime = meeting_datetime

async def test_complete_workflow():
    from services import PipefyService
    
    service = PipefyService()
    
    unique_email = f"complete.{datetime.now().strftime('%H%M%S')}@example.com"
    
    print(f"COMPLETE WORKFLOW TEST - Email: {unique_email}")
    print("=" * 70)
    
    # Step 1: Create a new card
    print("STEP 1: Creating new card...")
    lead1 = Lead(
        name="Initial Lead Name",
        email=unique_email,
        company="Initial Company",
        need="Initial requirement description",
        interest_confirmed=True
    )
    
    create_result = await service.create_or_update_lead(lead1)
    
    if create_result.get('data', {}).get('createCard', {}).get('card', {}).get('id'):
        card_id = create_result['data']['createCard']['card']['id']
        print(f"SUCCESS: Card created with ID: {card_id}")
        
        # Step 2: Update the same card
        print("\nSTEP 2: Updating the same card...")
        lead2 = Lead(
            name="Updated Lead Name",
            email=unique_email,
            company="Updated Company Name",
            need="Updated requirement with more detailed information",
            interest_confirmed=False,
            meeting_link="https://meet.google.com/successful-update",
            meeting_datetime=datetime(2024, 1, 25, 15, 30)
        )
        
        update_result = await service.create_or_update_lead(lead2)
        
        if update_result.get('success'):
            print(f"✅ SUCCESS: {update_result['message']}")
            print(f"   Successful updates: {update_result['successful_updates']}")
            if update_result.get('failed_updates'):
                print(f"   Failed updates: {update_result['failed_updates']}")
            print("🎉 COMPLETE WORKFLOW: SUCCESS - Create and Update both working!")
        else:
            print(f"❌ UPDATE FAILED: {update_result['message']}")
            
    elif create_result.get('errors'):
        print(f"❌ CREATION FAILED: {create_result['errors']}")
    else:
        print(f"❌ UNKNOWN RESULT: {create_result}")

async def test_individual_field_update():
    from services import PipefyService
    
    service = PipefyService()
    
    # Test with an existing card
    existing_email = "update.test.192251@example.com"
    
    print(f"\nINDIVIDUAL FIELD UPDATE TEST - Email: {existing_email}")
    print("=" * 70)
    
    result = await service._find_card_by_email(existing_email)
    cards = result.get('data', {}).get('cards', {}).get('edges', [])
    
    if cards:
        card_id = cards[0]['node']['id']
        print(f"Testing individual field update on card: {card_id}")
        
        # Test single field update
        test_result = await service._update_card_field(
            card_id, 
            "nome_do_lead", 
            "Individual Field Update Test"
        )
        
        if test_result.get('data', {}).get('updateCardField'):
            print("✅ SUCCESS: Individual field update working!")
            print(f"   Result: {test_result['data']['updateCardField']}")
        else:
            print(f"❌ Individual field update failed: {test_result}")

async def test_bulk_updates():
    from services import PipefyService
    
    service = PipefyService()
    
    # Test multiple existing cards
    test_emails = [
        "final.191708@example.com",
        "complete.191339@example.com", 
        "test.190955@example.com"
    ]
    
    print(f"\nBULK UPDATE TEST")
    print("=" * 70)
    
    for email in test_emails:
        print(f"\nUpdating card for: {email}")
        
        lead_update = Lead(
            name=f"Bulk Update Test - {datetime.now().strftime('%H:%M')}",
            email=email,
            company="Bulk Updated Company",
            need="This card was updated via bulk test",
            interest_confirmed=True,
            meeting_link="https://meet.google.com/bulk-test"
        )
        
        result = await service.create_or_update_lead(lead_update)
        
        if result.get('success'):
            print(f"✅ SUCCESS: {result['message']}")
        elif result.get('data', {}).get('createCard'):
            print("ℹ️  Created new card (no existing card found)")
        else:
            print(f"❌ FAILED: {result}")

if __name__ == "__main__":
    print("🚀 PIPEFY COMPLETE INTEGRATION TEST")
    print("=" * 70)
    print("Testing CREATE and UPDATE functionality...")
    
    asyncio.run(test_complete_workflow())
    asyncio.run(test_individual_field_update()) 
    asyncio.run(test_bulk_updates())
    
    print("\n" + "=" * 70)
    print("🎯 TESTING COMPLETED")
    print("Please check your Pipefy board to verify:")
    print("- New cards were created successfully") 
    print("- Existing cards were updated with new field values")
    print("- All fields are being populated correctly")