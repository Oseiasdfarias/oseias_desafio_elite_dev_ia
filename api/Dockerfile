# 1. Usar uma imagem base leve do Python
FROM python:3.10-slim

# --- ADICIONADO: Instalar e configurar o locale pt_BR ---
# Instala locales e suas dependências
RUN apt-get update && apt-get install -y locales \
    # Descomenta a linha pt_BR.UTF-8 no arquivo de configuração de locales
    && sed -i -e 's/# pt_BR.UTF-8 UTF-8/pt_BR.UTF-8 UTF-8/' /etc/locale.gen \
    # Gera o locale pt_BR.UTF-8
    && dpkg-reconfigure --frontend=noninteractive locales \
    # Limpa o cache do apt para reduzir o tamanho da imagem
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Define as variáveis de ambiente de locale para o container
ENV LANG pt_BR.UTF-8
ENV LANGUAGE pt_BR:pt
ENV LC_ALL pt_BR.UTF-8
# --------------------------------------------------------

# 2. Definir o diretório de trabalho dentro do contêiner
WORKDIR /app

# 3. Copiar o arquivo de dependências (Poetry) e instalar
# Copia primeiro para aproveitar o cache do Docker se não houver mudanças
COPY pyproject.toml poetry.lock ./
# Instala o Poetry e depois as dependências do projeto
RUN pip install --no-cache-dir poetry \
    && poetry config virtualenvs.create false \
    && poetry install --no-dev --no-interaction --no-ansi

# (Opcional: Se você ainda usa requirements.txt, descomente as linhas abaixo e comente as do Poetry)
# COPY requirements.txt .
# RUN pip install --no-cache-dir -r requirements.txt

# 4. Copiar todo o código do backend para o contêiner
# Isso inclui main.py, models.py, services/, etc.
COPY . .

# 5. Expor a porta que o Uvicorn usará
EXPOSE 8000

# 6. Comando para iniciar o servidor
#    (O host 0.0.0.0 é essencial para ser acessível fora do contêiner)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
