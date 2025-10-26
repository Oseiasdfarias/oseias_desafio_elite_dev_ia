# 1. Usar uma imagem base leve do Python
FROM python:3.10-slim

# 2. Definir o diretório de trabalho dentro do contêiner
WORKDIR /app

# 3. Copiar o arquivo de dependências e instalar
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copiar todo o código do backend para o contêiner
COPY . .

# 5. Expor a porta que o Uvicorn usará
EXPOSE 8000

# 6. Comando para iniciar o servidor
#    (O host 0.0.0.0 é essencial para ser acessível fora do contêiner)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]