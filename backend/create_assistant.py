import os
from dotenv import load_dotenv
from openai import OpenAI

def create_assistant():
    load_dotenv()
    print(f"OPENAI_API_KEY: {os.getenv('OPENAI_API_KEY')}")
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    assistant = client.beta.assistants.create(
        name="SDR Agent",
        instructions='''Você é um assistente SDR (Sales Development Representative) especialista em qualificação de leads e agendamento de reuniões. Seu tom é profissional, empático e proativo. NÃO FAÇA NENHUMA CONVERSÃO DE FUSO HORÁRIO.

            SEU FLUXO DE TRABALHO OBRIGATÓRIO:
            
            1.  **APRESENTAÇÃO:** Apresente-se e explique o serviço.
            2.  **COLETA (SCRIPT DE DESCOBERTA):** Colete nome, e-mail, empresa e necessidade.
            3.  **REGISTRO INICIAL:** Assim que tiver os 4 dados, chame `registrarLead`.
            4.  **GATILHO DA REUNIÃO:** Pergunte se o lead quer agendar.
            
            5.  **OFERECER HORÁRIOS:**
                - SE o lead confirmar interesse, chame `oferecerHorarios()`.
                - A função retornará uma lista de horários disponíveis já formatados para exibição (`available_slots_display`).
                - **APRESENTE** exatamente a lista de horários recebida para o usuário escolher. Liste de 3 a 5 opções.
                
            6.  **AGENDAR REUNIÃO:**
                - QUANDO o lead escolher um horário da lista (ex: "pode ser 28 de Outubro às 12:00"), chame a função `agendarReuniao`.
                - Use o parâmetro `data_inicio_display` para enviar **exatamente a string do horário escolhido pelo usuário**.
                - Inclua também `email_lead` e `nome_lead`.
                - A função retornará o link da reunião (`meeting_link`) e a hora confirmada formatada para exibição (`start_time_display`). Ela também retornará a hora em UTC (`start_time_utc`) para uso interno.
                - INFORME o lead sobre o sucesso, mostrando **exatamente** o `meeting_link` e a `start_time_display` recebidos.
                    Exemplo de Resposta: "Perfeito! Sua reunião está agendada para [start_time_display]. O link é: [meeting_link]" 
            
            7.  **ATUALIZAÇÃO FINAL (IMPORTANTE):** - Após o `agendarReuniao` ser bem-sucedido (retornar `success: True`), chame a função `registrarLead` NOVAMENTE.
                - Inclua o `meeting_link` retornado pela `agendarReuniao`.
                - Para o `meeting_datetime`, use **exatamente** a string `start_time_utc` retornada pela `agendarReuniao`.
            # --------------------------
            
            REGRAS ADICIONAIS:
            - Se o lead NÃO demonstrar interesse no passo 4, apenas agradeça e encerre.
            - Não repita perguntas já respondidas.
            - Se alguma função retornar um erro (`success: False`), informe o usuário sobre o problema e pergunte como proceder (ex: "Tive um problema ao [ação]. Quer tentar novamente?").
        ''',
        model="gpt-4o", # Recomendo fortemente o GPT-4o para esta lógica
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "registrarLead",
                    "description": "Registra ou ATUALIZA um lead no Pipefy. Chame após coletar dados iniciais e NOVAMENTE após agendar (se bem-sucedido) para adicionar detalhes da reunião.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "nome": {"type": "string", "description": "Nome completo do lead."},
                            "email": {"type": "string", "description": "E-mail do lead."},
                            "empresa": {"type": "string", "description": "Empresa do lead."},
                            "necessidade": {"type": "string", "description": "Necessidade principal."},
                            "interesse_confirmado": {"type": "boolean", "description": "Se o lead confirmou interesse em agendar."},
                            "meeting_link": {"type": "string", "description": "O link da reunião retornado por `agendarReuniao`."},
                            # Instrução clara sobre o formato esperado
                            "meeting_datetime": {"type": "string", "description": "A string 'start_time_utc' (formato ISO 8601 UTC) retornada por `agendarReuniao`."}
                        },
                        "required": ["nome", "email", "interesse_confirmado"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "oferecerHorarios",
                    "description": "Consulta a agenda e retorna uma lista de horários disponíveis formatados para exibição.",
                    "parameters": {
                        "type": "object",
                        "properties": {"dias": {"type": "integer", "description": "Número de dias (padrão: 7)."}},
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "agendarReuniao",
                    "description": "Agenda a reunião após o lead escolher um horário da lista apresentada.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            # Novo parâmetro para receber a escolha do usuário
                            "data_inicio_display": {"type": "string", "description": "A string EXATA do horário escolhido pelo usuário da lista apresentada (ex: '28 de Outubro às 12:00')."},
                            "email_lead": {"type": "string", "description": "E-mail do lead."},
                            "nome_lead": {"type": "string", "description": "Nome do lead."},
                        },
                        # Removido data_inicio e data_fim, substituído por data_inicio_display
                        "required": ["data_inicio_display", "email_lead", "nome_lead"],
                    },
                },
            },
        ],
    )

    print(f"Assistant ID: {assistant.id}")

    # Atualiza o .env (código igual ao anterior)
    env_lines = []
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            for line in f:
                if not line.startswith("OPENAI_ASSISTANT_ID="): env_lines.append(line)
    with open(".env", "w") as f:
        f.writelines(env_lines)
        if not env_lines or not env_lines[-1].endswith('\n'): f.write('\n')
        f.write(f"OPENAI_ASSISTANT_ID={assistant.id}\n")
    print("Arquivo .env atualizado com o novo ASSISTANT_ID.")

if __name__ == "__main__":
    create_assistant()
