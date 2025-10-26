import os
from dotenv import load_dotenv
from openai import OpenAI

def create_assistant():
    load_dotenv()
    print(f"OPENAI_API_KEY: {os.getenv('OPENAI_API_KEY')}")
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    assistant = client.beta.assistants.create(
        name="SDR Agent",
        instructions='''Você é um assistente SDR (Sales Development Representative) especialista em qualificação de leads e agendamento de reuniões. Seu tom é profissional, empático e proativo.

            SEU FLUXO DE TRABALHO OBRIGATÓRIO:
            
            1.  **APRESENTAÇÃO:** Apresente-se e explique o serviço (ex: "Olá! Sou o assistente virtual da [Sua Empresa] e estou aqui para ajudá-lo a [benefício do produto/serviço].").
            2.  **COLETA (SCRIPT DE DESCOBERTA):** Faça perguntas progressivas para coletar as informações básicas. NÃO FAÇA TODAS AS PERGUNTAS DE UMA VEZ. Seja natural.
                - Nome (ex: "Para começar, qual é o seu nome?")
                - E-mail (ex: "Obrigado, [Nome]. Qual é o seu e-mail comercial?")
                - Empresa (ex: "E para qual empresa você trabalha?")
                - Necessidade (ex: "Pode me contar um pouco sobre [sua dor/necessidade] atual?")
            3.  **REGISTRO INICIAL:** Assim que tiver nome, e-mail, empresa e necessidade, chame a função `registrarLead` para salvar o lead no Pipefy.
            4.  **GATILHO DA REUNIÃO (PERGUNTA DIRETA):** Após o registro, pergunte explicitamente: "Você gostaria de agendar uma conversa com nosso time especializado para discutir como podemos [resolver sua necessidade]?"
            5.  **OFERECER HORÁRIOS:**
                - SE o lead confirmar interesse (ex: "sim", "gostaria", "claro"), chame IMEDIATAMENTE a função `oferecerHorarios()`.
                - APRESENTE os horários retornados (ex: "Ótimo! Temos estes horários disponíveis: [lista]").
            6.  **AGENDAR REUNIÃO:**
                - QUANDO o lead escolher um horário específico (ex: "pode ser na terça às 10h"), chame a função `agendarReuniao` com os dados exatos do horário escolhido.
                - INFORME o lead sobre o sucesso (ex: "Perfeito! Agendado. Você receberá o link da reunião no seu e-mail.")
            7.  **ATUALIZAÇÃO FINAL (IMPORTANTE):** Após o `agendarReuniao` ser bem-sucedido, chame a função `registrarLead` NOVAMENTE, incluindo o `meeting_link` e `meeting_datetime` para ATUALIZAR o card no Pipefy.
            
            REGRAS ADICIONAIS:
            - Se o lead NÃO demonstrar interesse no passo 4, apenas agradeça e encerre cordialmente (o registro inicial no passo 3 já foi feito).
            - Não repita perguntas já respondidas.
        ''',
        model="gpt-3.5-turbo", # Considere usar "gpt-4-turbo" para melhores resultados em seguir fluxos complexos
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "registrarLead",
                    "description": "Registra ou ATUALIZA um lead no Pipefy. Use isso uma vez após coletar os dados iniciais e NOVAMENTE após agendar uma reunião para adicionar os detalhes do agendamento.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "nome": {"type": "string", "description": "Nome completo do lead."},
                            "email": {"type": "string", "description": "E-mail do lead."},
                            "empresa": {"type": "string", "description": "Empresa do lead."},
                            "necessidade": {"type": "string", "description": "Necessidade ou dor principal do lead."},
                            "interesse_confirmado": {"type": "boolean", "description": "Indica se o lead confirmou explicitamente o interesse em agendar a reunião."},
                            "meeting_link": {"type": "string", "description": "O link da reunião (Google Meet, etc.) retornado por `agendarReuniao`."},
                            "meeting_datetime": {"type": "string", "description": "Data e hora da reunião no formato ISO 8601 (ex: '2025-10-28T10:00:00')"}
                        },
                        "required": ["nome", "email", "interesse_confirmado"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "oferecerHorarios",
                    "description": "Consulta a API de agenda para obter horários disponíveis nos próximos dias. Chame APENAS DEPOIS que o lead confirmar interesse.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "dias": {"type": "integer", "description": "Número de dias a serem considerados (padrão: 7)."}
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "agendarReuniao",
                    "description": "Agenda a reunião após o lead escolher um slot específico.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "data_inicio": {"type": "string", "description": "Data e hora de início da reunião no formato ISO 8601, obtida de `oferecerHorarios`."},
                            "data_fim": {"type": "string", "description": "Data e hora de término da reunião no formato ISO 8601, obtida de `oferecerHorarios`."},
                            "email_lead": {"type": "string", "description": "E-mail do lead para associar à reunião."},
                            "nome_lead": {"type": "string", "description": "Nome do lead para a reunião."},
                        },
                        "required": ["data_inicio", "data_fim", "email_lead", "nome_lead"],
                    },
                },
            },
        ],
    )

    print(f"Assistant ID: {assistant.id}")

    # Atualiza o .env
    env_lines = []
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            for line in f:
                if not line.startswith("OPENAI_ASSISTANT_ID="):
                    env_lines.append(line)
                    
    with open(".env", "w") as f:
        f.writelines(env_lines)
        if not env_lines or not env_lines[-1].endswith('\n'):
             f.write('\n')
        f.write(f"OPENAI_ASSISTANT_ID={assistant.id}\n")
    
    print("Arquivo .env atualizado com o novo ASSISTANT_ID.")


if __name__ == "__main__":
    create_assistant()
