# togglemaster-cicd-templates

Catálogo central de templates GitHub Actions da plataforma ToggleMaster.

## Templates disponíveis

Cada estágio da pipeline possui seu próprio workflow reutilizável:

- `validate.yml`: build, teste e lint por linguagem.
- `security.yml`: SCA com Trivy, SAST com gosec ou bandit e SonarCloud opcional.
- `image.yml`: build, scan da imagem e push no Amazon ECR somente na `main`.
- `update-gitops.yml`: atualização da tag da imagem no repositório GitOps após o push bem-sucedido.

Os templates possuem cache de dependências e autenticação AWS via OIDC. O repositório consumidor define a concorrência e o encadeamento entre estágios.

## Consumo

Cada repositório de aplicação mantém apenas workflows adaptadores para definir eventos, concorrência, parâmetros e dependências entre os estágios:

```yaml
jobs:
	validate:
		uses: jhouzera/togglemaster-cicd-templates/.github/workflows/validate.yml@main
		with:
			service-name: auth-service
			service-language: go
			service-path: app/auth-service

	security:
		needs: validate
		uses: jhouzera/togglemaster-cicd-templates/.github/workflows/security.yml@main
		with:
			service-name: auth-service
			service-language: go
			service-path: app/auth-service
		secrets: inherit

	image:
		needs: security
		uses: jhouzera/togglemaster-cicd-templates/.github/workflows/image.yml@main
		with:
			service-name: auth-service
			service-path: app/auth-service
			service-dockerfile: app/auth-service/Dockerfile
			aws-region: us-east-1
			role-to-assume: arn:aws:iam::ACCOUNT_ID:role/github-actions-ecr-push-role
			push-images: ${{ github.event_name == 'push' && github.ref == 'refs/heads/main' }}

	update-gitops:
		needs: image
		uses: jhouzera/togglemaster-cicd-templates/.github/workflows/update-gitops.yml@main
		with:
			service-name: auth-service
			push-images: ${{ github.event_name == 'push' && github.ref == 'refs/heads/main' }}
			gitops-values-file: charts/togglemaster/apps/auth-values.yaml
		secrets: inherit
```

## Secrets exigidos pelo consumidor

- `GITOPS_TOKEN`: token com escrita no repositório GitOps.
- `GITOPS_REPO`: proprietário e nome do repositório GitOps.
- `GITOPS_BRANCH`: branch GitOps; usa `main` quando vazio.
- `SONAR_TOKEN`: opcional; habilita o scan SonarCloud.

## Versionamento

Os consumidores usam `@main` enquanto o catálogo é inicializado. Após publicar a primeira versão, crie e mantenha a tag major `v1`; os consumidores devem então referenciar `@v1` ou, para máxima rastreabilidade, o SHA de um release.

## Configuração no GitHub

Se este repositório for privado, em **Settings > Actions > General > Access** habilite o acesso para os repositórios privados do proprietário. Sem essa permissão, os callers não conseguem resolver o workflow reutilizável, mesmo que o caminho e a referência estejam corretos.