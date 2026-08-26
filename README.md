# All Web Down

Uma interface minimalista para identificar formatos disponíveis em links públicos de mídia e iniciar o download sem sair da página.

## Como funciona

- O navegador envia o link para `/api/analyze`.
- Uma função Python usa `yt-dlp` para identificar a origem e listar formatos reais.
- O usuário escolhe qualidade ou formato.
- `/api/download` prepara o arquivo e o devolve com `Content-Disposition: attachment`, mantendo a interface aberta.

O projeto não usa banco de dados, não mantém histórico e não aceita conteúdo privado ou protegido por DRM. Baixe apenas conteúdo que você tem autorização para salvar.

## Desenvolvimento

```bash
npm run check
vercel dev
```

## Deploy

O projeto é compatível com Vercel sem configuração adicional. As funções Python e os arquivos estáticos são detectados automaticamente.

