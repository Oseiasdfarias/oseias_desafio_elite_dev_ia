# --- Estágio 1: Build (Construção) ---
FROM node:18-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm install
COPY . .
RUN npm run build

# --- Estágio 2: Serve (Servidor) ---
FROM nginx:stable-alpine

# --- ADICIONE ESTAS DUAS LINHAS ---
# Atualiza todos os pacotes para as versões mais recentes
# Isso corrige vulnerabilidades conhecidas nas bibliotecas do Alpine
RUN apk update && apk upgrade
# ------------------------------------

# Copia os arquivos estáticos construídos do estágio 1
COPY --from=build /app/build /usr/share/nginx/html

# Copia nossa configuração de proxy reverso (próximo passo)
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Expõe a porta 80 (padrão do Nginx)
EXPOSE 80

# Comando para iniciar o Nginx
CMD ["nginx", "-g", "daemon off;"]