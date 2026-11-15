# Deployment guide (Vultr, Tiger Cloud, domain, Gemini)

Production is one Vultr VM running the backend container and Caddy, a Tiger Cloud database, and a registered
domain. You set up the accounts once; `make deploy` does the rest.

## 1. Vultr VM

1. vultr.com → Products → Compute → Deploy → Cloud Compute (Shared CPU).
2. Image **Ubuntu 24.04 LTS x64**. Plan **2 vCPU / 4 GB RAM** or more (the simulation, SHAP and the federated run need it).
3. Add your SSH public key (`cat ~/.ssh/id_ed25519.pub`, or create one with `ssh-keygen -t ed25519`).
4. Deploy, then copy the IP address.
5. Firewall group: allow inbound TCP 22, 80 and 443 and attach it to the VM.
6. First login:

   ```sh
   ssh root@<VM_IP>
   apt update && apt upgrade -y
   adduser deploy && usermod -aG sudo deploy
   mkdir -p /home/deploy/.ssh && cp ~/.ssh/authorized_keys /home/deploy/.ssh/ && chown -R deploy:deploy /home/deploy/.ssh
   curl -fsSL https://get.docker.com | sh
   usermod -aG docker deploy
   ```

   Open a new terminal and check that `ssh deploy@<VM_IP>` and `docker run hello-world` work.

## 2. Domain

Register the domain, then add an **A record** (and `www` if wanted) pointing at the VM IP. Check with
`dig +short yourdomain`; Caddy cannot get a certificate until it prints the VM IP.

## 3. Tiger Cloud

Create a TimescaleDB service at tigerdata.com, allow connections from the VM IP and from your Mac, and copy the
connection string (`postgres://tsdbadmin:PASSWORD@HOST:PORT/tsdb?sslmode=require`).

## 4. Gemini

Create an API key in Google AI Studio and choose the model name (it is read from `GEMINI_MODEL`).

## 5. Configure and deploy

1. On your Mac: `cp .env.deploy.example .env.deploy` and fill in `DEPLOY_HOST`, `DOMAIN`, `PROD_DATABASE_URL`.
2. Create `.env.prod` (gitignored) with the VM's settings, or create `~/hospital-twin/.env` on the VM yourself:

   ```
   DATABASE_URL=<Tiger Cloud string>
   DOMAIN=<your domain>
   GEMINI_API_KEY=<key>
   GEMINI_MODEL=<model name>
   ```

3. `make seed-prod` migrates the Tiger Cloud database and loads the Synthea patients from your Mac (needs `make setup`).
4. `make train` once (it writes `data/ml/train.parquet`, which `make deploy` copies for the federated button).
5. `make deploy`: copies the project, builds the images, starts the stack, runs the migrations and smoke-checks
   `https://<domain>` (health, page, WebSocket snapshot). Certificates can take a minute.

`make smoke URL=https://<domain>` repeats the check at any time. Logs: `ssh deploy@<VM_IP> "cd hospital-twin &&
docker compose -f infra/docker-compose.prod.yml --env-file .env logs --tail=100"`.

## Optional: a local model when Gemini fails or hangs

Ollama needs no API key. In `.env.prod` add:

```
COMPOSE_PROFILES=ollama
OLLAMA_URL=http://ollama:11434
OLLAMA_MODEL=qwen2.5:1.5b
```

Run `make deploy`, then pull the model once (about 1 GB; the 4 GB VM can hold it next to the backend):

```
ssh deploy@<VM_IP> "cd hospital-twin && docker compose -f infra/docker-compose.prod.yml --env-file .env exec ollama ollama pull qwen2.5:1.5b"
```

The agent then tries Gemini, then the local model, then the rules engine. Ask Hospital Twin falls back to its
deterministic parser (small local models are not reliable enough at calling tools). Replies from the local model go
through the same grounding check as Gemini's.
