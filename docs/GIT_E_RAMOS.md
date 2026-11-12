# Git e ramos

1. `ferramentas\INICIAR_GIT.bat` cria o repositório local (branch `main`) e o primeiro commit. Se faltar o nome/email do Git, diz-te o comando.
2. GitHub (mais tarde, **repositório privado**): `git remote add origin <url>` e `git push -u origin main`.
3. Fluxo proposto: `main` = estável testada. Cada alteração nasce num ramo (`git switch -c nome-da-alteracao`), testa-se com `ARRANCAR_DASHBOARD_2.0.bat` (porta 22396, sem tocar na produção) e só depois se faz *merge*.
4. **Promover para produção** (quando decidirem): gerar um ZIP de atualização com o instalador que já existe (backup + rollback automático) a partir dos ficheiros alterados. Nunca copiar `runtime/` por cima da produção.
5. Ficheiros grandes (`7_painel_web/assets`, ~23 MB de texturas do avatar): aceitáveis agora; se o repositório pesar, passar a Git LFS.
