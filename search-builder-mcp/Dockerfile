FROM node:20-slim

WORKDIR /app

COPY package.json tsconfig.json ./
COPY src ./src

RUN npm install
RUN npm run build

ENV PORT=9000
ENV SEARCH_BUILDER_API_BASE=http://ingest-api:8080

EXPOSE 9000

CMD ["npm", "run", "start"]
