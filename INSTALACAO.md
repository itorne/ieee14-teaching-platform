# Como instalar e abrir a plataforma (alunos)

Repositório: **https://github.com/itorne/ieee14-teaching-platform**

Tempo: cerca de 15 minutos na primeira vez. É preciso internet só na instalação.

## 1. Instalar o Python 3.14 (uma única vez)

1. Acesse https://www.python.org/downloads/ e clique em **Download** na linha **3.14** e baixe o **Windows installer (64-bit)**. Não use a 3.15 (ainda sem todos os pacotes) nem a 3.13 (o site não oferece mais instalador para Windows).
2. **Windows:** na primeira tela do instalador, marque **"Add python.exe to PATH"** e clique em **"Install Now"**.
3. **macOS:** execute o instalador `.pkg` normalmente.
4. **Linux:** instale pelo gerenciador de pacotes (por exemplo, `sudo apt install python3.14 python3.14-venv`).

## 2. Baixar a plataforma

Escolha **uma** das opções:

- **Sem Git (mais simples):** abra https://github.com/itorne/ieee14-teaching-platform, clique no botão verde **"Code"** e depois em
  **"Download ZIP"**. Extraia o arquivo em uma pasta fácil de achar, por exemplo `Documentos\plataforma-ieee14`
  (clique com o botão direito no ZIP → **"Extrair tudo"**). Não execute a plataforma de dentro do ZIP.
- **Com Git:** abra o terminal na pasta desejada e execute
  `git clone https://github.com/itorne/ieee14-teaching-platform.git`

## 3. Abrir a plataforma

- **Windows:** abra a pasta da plataforma e dê **dois cliques em `iniciar.bat`**.
  Se o Windows mostrar "O Windows protegeu o computador", clique em **"Mais informações" → "Executar assim mesmo"**.
- **macOS/Linux:** abra o terminal na pasta e execute `./iniciar.sh`
  (na primeira vez, se necessário, `chmod +x iniciar.sh`).

Na **primeira vez** o script instala tudo sozinho (3 a 10 minutos). Depois disso, a plataforma abre em
segundos. O navegador abre em **http://localhost:8501**; se não abrir, digite esse endereço no navegador.

Para **encerrar**, feche a janela preta (Windows) ou pressione `Ctrl+C` no terminal.

## 4. Teste antes da aula

Abra a plataforma em casa antes da aula. Você deve ver o título **"IEEE 14-bus operation panel"**, o diagrama
da rede e o botão **"▶ Next hour"**. Traga o computador carregado no dia da atividade.

## Problemas comuns

| Problema | Solução |
|---|---|
| "Python não encontrado" | Reinstale o Python 3.14 marcando "Add python.exe to PATH". |
| "Falha na instalação" | Verifique a internet e execute `iniciar.bat` de novo. |
| O navegador não abriu | Digite http://localhost:8501 no navegador. |
| "Port 8501 is already in use" | A plataforma já está aberta em outra janela; use-a ou feche-a. |
| Antivírus bloqueou o script | Permita a execução ou peça ajuda ao professor. |
| Tela em branco por muito tempo | Aguarde a primeira execução terminar e recarregue a página (F5). |
