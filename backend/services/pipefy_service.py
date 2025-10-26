import os
import asyncio
import httpx
from datetime import datetime
from typing import List, Dict, Any
import json

from models import Lead

class PipefyService:
    """
    Serviço para integração com a API da Pipefy
    Gerencia criação e atualização de cards no pipe de leads
    """
    
    def __init__(self):
        self.api_key = os.getenv("PIPEFY_API_KEY")
        self.pipe_id = os.getenv("PIPEFY_PIPE_ID")
        self.api_url = "https://api.pipefy.com/graphql"

        # Carrega IDs de campos do .env
        self.field_id_name = os.getenv("PIPEFY_NAME_FIELD_ID", "nome_do_lead")
        self.field_id_email = os.getenv("PIPEFY_EMAIL_FIELD_ID", "e_mail")
        self.field_id_company = os.getenv("PIPEFY_COMPANY_FIELD_ID", "empresa")
        self.field_id_need = os.getenv("PIPEFY_NEED_FIELD_ID", "necessidade_espec_fica")
        self.field_id_interest = os.getenv("PIPEFY_INTEREST_FIELD_ID", "checklist_vertical")
        self.field_id_meeting_link = os.getenv("PIPEFY_MEETING_LINK_FIELD_ID", "link_da_reuni_o")
        self.field_id_meeting_time = os.getenv("PIPEFY_MEETING_TIME_FIELD_ID", "data_e_hora_da_reuni_o")
        
        # Nome do campo de email (para busca)
        self.email_field_name = os.getenv("PIPEFY_EMAIL_FIELD_NAME", "E-mail")

        if not all([self.api_key, self.pipe_id, self.field_id_email]):
            raise ValueError("Pipefy environment variables are not properly configured (PIPEFY_API_KEY, PIPEFY_PIPE_ID, PIPEFY_EMAIL_FIELD_ID)")
            
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        self.client = httpx.AsyncClient(timeout=30.0)

    async def _execute_query(self, query: str) -> Dict[str, Any]:
        """Executa uma query GraphQL na API da Pipefy de forma assíncrona"""
        try:
            response = await self.client.post(
                self.api_url, 
                headers=self.headers, 
                json={"query": query}
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            print(f"Pipefy API HTTP error: {e.response.status_code} - {e.response.text}")
            return {"errors": [{"message": f"HTTP error: {e.response.status_code}"}]}
        except httpx.RequestError as e:
            print(f"Pipefy API request error: {e}")
            return {"errors": [{"message": f"Request error: {str(e)}"}]}
        except Exception as e:
            print(f"Pipefy API unexpected error: {e}")
            return {"errors": [{"message": str(e)}]}

    async def _find_card_by_email(self, email: str) -> Dict[str, Any]:
        """Encontra cards existentes pelo email"""
        # Esta query busca os últimos 50 cards. Para produção, considere uma busca mais robusta.
        query = f'''
        {{
            cards(pipe_id: {self.pipe_id}, first: 50) {{
                edges {{
                node {{
                    id
                    title
                    fields {{
                    name
                    value
                    }}
                }}
                }}
            }}
        }}
        '''
        
        result = await self._execute_query(query)
        
        if result.get('errors'):
            return result
            
        cards_found = []
        edges = result.get('data', {}).get('cards', {}).get('edges', [])
        
        for edge in edges:
            card = edge['node']
            for field in card.get('fields', []):
                # Usa a variável de ambiente para o NOME do campo
                if field.get('name') == self.email_field_name and field.get('value') == email:
                    cards_found.append(card)
                    break
        
        return {
            'data': {
                'cards': {
                    'edges': [{'node': card} for card in cards_found]
                }
            }
        }
    
    async def _update_card_field(self, card_id: str, field_id: str, value: Any) -> Dict[str, Any]:
        """Atualiza um campo individual de um card"""
        
        # Usa a mesma formatação de valor
        formatted_value = self._format_field_value(value)
        
        mutation = f'''
        mutation {{
            updateCardField(input: {{
                card_id: "{card_id}",
                field_id: "{field_id}",
                new_value: {formatted_value}
            }}) {{
                card {{
                id
                title
                }}
                success
            }}
        }}
        '''
        
        return await self._execute_query(mutation)

    def _format_field_value(self, value):
        """Escapa aspas e caracteres especiais para a query GraphQL"""
        if isinstance(value, str):
            return json.dumps(value) # json.dumps lida com aspas, \n, etc.
        if isinstance(value, bool):
            return '"Confirmado"' if value else '"Não confirmado"'
        if isinstance(value, datetime):
            return f'"{value.isoformat()}"'
        if value is None:
            return None
        return f'"{str(value)}"'


    async def _create_card(self, lead: Lead) -> Dict[str, Any]:
        """Cria um novo card no pipe"""
        
        fields_map = {
            self.field_id_name: lead.name or "Lead (Nome Pendente)",
            self.field_id_email: lead.email,
            self.field_id_company: lead.company or "Empresa não informada",
            self.field_id_need: lead.need or "Interesse em nossos serviços",
            self.field_id_interest: "Confirmado" if lead.interest_confirmed else "Não confirmado",
            self.field_id_meeting_link: lead.meeting_link,
            self.field_id_meeting_time: lead.meeting_datetime.isoformat() if lead.meeting_datetime else None
        }

        fields_array = []
        for field_id, value in fields_map.items():
            if value is not None:
                formatted_value = self._format_field_value(value)
                fields_array.append(f'{{field_id: "{field_id}", field_value: {formatted_value}}}')

        fields_str = ", ".join(fields_array)
        
        mutation = f'''
        mutation {{
            createCard(input: {{
                pipe_id: {self.pipe_id},
                title: "{lead.name or 'Novo Lead'} - {lead.email}",
                fields_attributes: [
                {fields_str}
                ]
            }}) {{
                card {{
                id
                title
                }}
            }}
        }}
        '''
        
        print(f"Pipefy Create Mutation: {mutation}")
        result = await self._execute_query(mutation)
        print(f"Pipefy Create Response: {result}")
        return result

    async def _update_card_fields(self, card_id: str, lead: Lead) -> Dict[str, Any]:
        """Atualiza todos os campos de um card existente (um por um, em paralelo)"""
        
        # Mapeia os campos do Pydantic para os IDs de campo do Pipefy
        field_mapping = {
            self.field_id_name: lead.name,
            self.field_id_email: lead.email,
            self.field_id_company: lead.company,
            self.field_id_need: lead.need,
            self.field_id_interest: "Confirmado" if lead.interest_confirmed else "Não confirmado",
            self.field_id_meeting_link: lead.meeting_link,
            self.field_id_meeting_time: lead.meeting_datetime.isoformat() if lead.meeting_datetime else None
        }
        
        successful_updates = []
        failed_updates = []
        
        tasks = []
        for field_id, value in field_mapping.items():
            if value is not None:
                # Cria uma tarefa para cada atualização de campo
                tasks.append(self._update_card_field(card_id, field_id, value))
        
        # Executa todas as atualizações em paralelo
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Coleta os resultados
        field_ids = [fid for fid, val in field_mapping.items() if val is not None]
        for i, result in enumerate(results):
            field_id = field_ids[i]
            if isinstance(result, Exception):
                print(f"Error updating field {field_id}: {result}")
                failed_updates.append(field_id)
            elif result.get('data', {}).get('updateCardField', {}).get('success'):
                successful_updates.append(field_id)
            else:
                print(f"Failed to update field {field_id}: {result.get('errors')}")
                failed_updates.append(field_id)
        
        if successful_updates:
            return {
                'success': True,
                'message': f'Successfully updated {len(successful_updates)} fields',
                'card_id': card_id,
                'successful_updates': successful_updates,
                'failed_updates': failed_updates
            }
        else:
            return {
                'success': False,
                'message': 'All field updates failed',
                'card_id': card_id,
                'errors': [str(e) for e in results if isinstance(e, Exception)]
            }

    async def create_or_update_lead(self, lead: Lead) -> Dict[str, Any]:
        """
        Cria ou atualiza um lead no Pipefy
        """
        try:
            if not lead.email:
                return {"success": False, "error": "Email is required to create or update a lead"}

            existing_card_data = await self._find_card_by_email(lead.email)
            
            if existing_card_data.get('errors'):
                return {"success": False, "error": "Search failed", "details": existing_card_data['errors']}
            
            cards_edges = existing_card_data.get("data", {}).get("cards", {}).get("edges", [])
            
            if cards_edges:
                card_id = cards_edges[0]["node"]["id"]
                print(f"Found existing card {card_id} for email {lead.email}. Updating...")
                return await self._update_card_fields(card_id, lead)
            else:
                print(f"No card found for email {lead.email}. Creating new card...")
                result = await self._create_card(lead)
                if result.get('data', {}).get('createCard'):
                    return {
                        'success': True,
                        'message': 'Card created successfully',
                        'card_id': result['data']['createCard']['card']['id']
                    }
                else:
                    return {
                        'success': False,
                        'message': 'Failed to create card',
                        'errors': result.get('errors', [])
                    }
        except Exception as e:
            print(f"Error in create_or_update_lead: {e}")
            return {"success": False, "error": str(e)}

    async def close(self):
        """Fecha o client HTTP"""
        await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
