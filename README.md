# RotaHub

Otimizador de rotas de entrega para as planilhas exportadas pela Shopee / Rota
Shopee / Circuit Route Planner. Feito sob medida para 3 usuÃ¡rios fixos
(Matheus, Bruna, Paulo) â€” sem cadastro pÃºblico.

## O diferencial

O Circuit (e apps parecidos) costumam gerar rotas com **voltas
desnecessÃ¡rias**: visitam uma rua, seguem para outro bairro, e depois voltam
Ã  mesma rua. Isso acontece porque usam heurÃ­sticas gulosas (vizinho mais
prÃ³ximo), que otimizam passo a passo sem enxergar a rota inteira.

O RotaHub resolve isso com:
- **OSRM** para calcular distÃ¢ncia/tempo **reais de rua** entre todas as
  paradas (nÃ£o linha reta) â€” com fallback automÃ¡tico em Haversine se o OSRM
  estiver indisponÃ­vel.
- **Google OR-Tools** (Guided Local Search) para resolver o problema como um
  TSP de verdade, minimizando a distÃ¢ncia **total** da rota, nÃ£o sÃ³ o
  prÃ³ximo passo.

Nos testes com a planilha real fornecida (63 paradas), isso reduziu a
distÃ¢ncia percorrida em **~35%** comparado Ã  ordem "crua" de importaÃ§Ã£o.

## Estrutura

```
rotahub/
â”œâ”€â”€ backend/          FastAPI + SQLite + OR-Tools
â”‚   â””â”€â”€ app/
â”‚       â”œâ”€â”€ main.py       endpoints da API (RF001-RF015)
â”‚       â”œâ”€â”€ parser.py     importaÃ§Ã£o de .xlsx (2 formatos suportados)
â”‚       â”œâ”€â”€ geo.py        clustering por proximidade + geocodificaÃ§Ã£o fallback
â”‚       â”œâ”€â”€ distance.py   matriz de distÃ¢ncia (OSRM com fallback Haversine)
â”‚       â”œâ”€â”€ optimizer.py  TSP com OR-Tools
â”‚       â”œâ”€â”€ auth.py       login com JWT (3 usuÃ¡rios fixos)
â”‚       â””â”€â”€ models.py     Route -> Stop -> Package
â””â”€â”€ frontend/         HTML + CSS + JS puro (sem build step), mapa com Leaflet
```

## Como rodar localmente

```bash
cd backend
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Abra **http://localhost:8000** no navegador â€” o prÃ³prio backend jÃ¡ serve o
frontend.

### UsuÃ¡rios fixos (RF001)

| UsuÃ¡rio | Senha        |
|---------|--------------|
| matheus | rotahub2026  |
| bruna   | rotahub2026  |
| paulo   | rotahub2026  |

**Troque essas senhas antes de publicar** (edite `backend/app/database.py`,
funÃ§Ã£o `init_db`, e apague `rotahub.db` para recriar os usuÃ¡rios).

## Formatos de planilha aceitos (RF003)

O parser detecta automaticamente qual dos dois formatos foi enviado:

1. **Shopee bruto** â€” colunas `AT ID, Sequence, Stop, SPX TN, Destination
   Address, Bairro, City, Zipcode/Postal code, Latitude, Longitude`. Uma
   linha = um pacote.
2. **Circuit processado** â€” colunas `AT ID, Destination Address, Bairro,
   City, Zipcode/Postal code, Latitude, Longitude, Address Line 2, Pacotes na
   Parada`. Uma linha = uma parada, com pacotes agregados numa string.

Em ambos os casos, as paradas sÃ£o reagrupadas **pela coordenada real**
(tolerÃ¢ncia ~25m) e nÃ£o pelo campo `Stop` da planilha, que provou ser
inconsistente na planilha real analisada.

## SeguranÃ§a

- Senhas com hash bcrypt (nunca texto puro).
- JWT com chave persistida entre reinÃ­cios do servidor (variÃ¡vel de ambiente
  `ROTAHUB_SECRET_KEY` recomendada em produÃ§Ã£o).
- Upload de planilha limitado a 8MB e apenas `.xlsx`.
- CORS restrito (configurÃ¡vel via `ROTAHUB_CORS_ORIGINS`).

## Hospedagem gratuita sugerida

- **Backend + frontend juntos**: [Render.com](https://render.com) (Web
  Service free tier) â€” o prÃ³prio FastAPI jÃ¡ serve os arquivos estÃ¡ticos, um
  serviÃ§o sÃ³ resolve tudo.
- **Banco**: SQLite Ã© suficiente para 3 usuÃ¡rios e volume de uma rota diÃ¡ria;
  o disco do Render free tier Ã© efÃªmero em alguns planos â€” se isso for
  problema, trocar para PostgreSQL free tier (Neon/Supabase) Ã© uma mudanÃ§a
  pequena (sÃ³ a `DATABASE_URL` em `database.py`).

## VerificaÃ§Ã£o de endereÃ§os (RF005)

ApÃ³s importar a planilha, o botÃ£o **"Verificar endereÃ§os"** checa se as
coordenadas das paradas batem com o endereÃ§o real - usando 3 camadas
gratuitas, sem depender de APIs pagas:

1. **Nominatim reverso** (OpenStreetMap) â€” da coordenada da planilha,
   pergunta ao OSM "que endereÃ§o tem aqui?". Mais confiÃ¡vel que tentar
   achar por texto, porque o OSM indexa por posiÃ§Ã£o.
2. **BrasilAPI / ViaCEP** â€” quando a parada tem CEP, valida se a
   coordenada do CEP confere com a da planilha.
3. **Nominatim forward** (fallback) â€” se as camadas acima nÃ£o
   conseguiram verificar, tenta achar o endereÃ§o textualmente no OSM.

Paradas com divergÃªncia aparecem com um Ã­cone âš  e um link ðŸ“ que abre
a coordenada no Google Maps para conferÃªncia visual.

Para no futuro escalar para algo mais preciso, basta definir a
variÃ¡vel de ambiente `ROTAHUB_GOOGLE_GEOCODING_KEY` com uma chave do
Google Cloud (Geocoding API) â€” o sistema automÃ¡ticamente passa a
usar o Google como fonte primÃ¡ria, mantendo o Nominatim como fallback.

## O que falta para produÃ§Ã£o

- ~~Editar endereÃ§os marcados como `needs_review` diretamente na UI~~
  âœ… Endpoints `PUT /stops/{id}/address` e `PUT /stops/{id}/location` +
  botÃ£o de verificaÃ§Ã£o implementados.
- ~~Testes automatizados~~ âœ… 48 testes cobrindo parser, auth, database,
  endpoints REST, fluxo completo de entrega e rate limiting.
- ~~Rate limiting no endpoint de login~~ âœ… Implementado (5/min via slowapi).


## Acessar do celular (4G ou WiFi) com HTTPS

O RotaHub roda no seu PC. Para acessar do celular da Bruna, Paulo ou seu -
tanto em casa (WiFi) quanto na rua (4G) - voce precisa expor o servidor local
na internet com HTTPS. O HTTPS e necessario porque a API de geolocalizacao
do navegador celular so funciona em HTTPS (nao em HTTP).

Usamos o tunel gratuito do Cloudflare (cloudflared), que e estavel, sem
timeout agressivo e nao exige cadastro.

### Primeira vez: baixar o cloudflared

O binario ja vem na pasta do projeto como cloudflared.exe. Se nao estiver
la, baixe manualmente em:

https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe

e salve como cloudflared.exe na raiz do projeto (ao lado de un.bat).

### Como subir (passo a passo)

1. No PC do Matheus, abra um terminal e rode:

   ```
   run.bat
   ```

   Isso sobe o RotaHub em http://localhost:8000 (deixe esse terminal aberto).

2. Abra OUTRO terminal (segundo) e rode:

   ```
   expose.bat
   ```

   O cloudflared vai subir um tunel e imprimir uma URL HTTPS na tela, algo
   como:

   ```
   https://xxxx-xxxx-xxxx.trycloudflare.com
   ```

3. Copie essa URL e mande para a Bruna e o Paulo (WhatsApp, Telegram, etc).

4. Eles abrem no navegador do celular. A tela de login aparece, eles entram
   com usuario/senha (matheus/bruna/paulo, senha otahub2026).

5. O mapa e a geolocalizacao funcionam no celular porque a URL e HTTPS.

### Regras e limitacoes

- **PC ligado**: o seu PC precisa ficar ligado sempre que alguem for usar o
  app. Se o PC desligar, o tunel cai junto e os celulares perdem acesso.
- **URL muda a cada restart**: cada vez que voce reinicia o expose.bat,
  uma URL nova e gerada. Avise a equipe quando isso acontecer. Para URL fixa
  gratuita, verifique a secao "Tunel nomeado" abaixo.
- **Acesso nao e publico**: embora a URL seja publica na internet, o RotaHub
  exige login (matheus/bruna/paulo). Quem descobrir a URL sem senha nao
  consegue usar.
- **Uso nao comercial**: o plano gratuito do Cloudflare permite uso pessoal
  e nao comercial, que e o caso do RotaHub.

### Tunel nomeado (URL fixa, opcional)

Se a URL mudando toda hora incomodar, voce pode criar um tunel nomeado
gratuito com URL fixa (ex: otahub.suaempresa.com). Exige:

1. Ter um dominio proprio (registrado em algum lugar tipo Namecheap,
   Registro.br ~R$ 40/ano em .com.br)
2. Criar conta na Cloudflare e vincular o dominio a ela (gratis)
3. Rodar cloudflared tunnel login e seguir o Wizard
4. Criar o tunel: cloudflared tunnel create rotahub
5. Configurar a rota DNS: cloudflared tunnel route dns rotahub rotahub.suaempresa.com
6. Rodar: cloudflared tunnel run rotahub

Para o tempo de projeto um-tres usuarios, o tunel quick (URL que muda) e
suficiente. Migre para o nomeado so se a redefinicao comecar a incomodar.

### Solucao de problemas

**"Nao consigo achar a URL no log"** - procure por uma linha parecida com:

  Your quick Tunnel has been created! Visit it at: https://xxxx-xxxx-xxxx.trycloudflare.com

**"O celular acessa mas o GPS nao funciona"** - confirme que a URL comeca
com https:// (nao http://). Se nao for HTTPS, o GPS do navegador e
bloqueado.

**"A URL parou de funcionar no meio do dia"** - o tunel quick pode cair
raramente. Reinicie o expose.bat pegue a nova URL.