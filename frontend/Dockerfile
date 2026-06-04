FROM node:20-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
# Ensure local CLI binaries are executable (alpine sometimes drops the bit).
RUN chmod +x node_modules/.bin/* && npm run build

FROM nginx:1.27-alpine
# nginx official image runs envsubst on /etc/nginx/templates/*.template at start.
COPY default.conf.template /etc/nginx/templates/default.conf.template
ENV BACKEND_UPSTREAM=http://backend:8000
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
