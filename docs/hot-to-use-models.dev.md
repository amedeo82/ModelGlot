#How to use

Models.dev is a comprehensive open-source database of AI model specifications, pricing, and features.

The homepage starts with provider-agnostic model metadata. Model pages list the providers serving that model; provider pages list every model available from that provider; lab pages group canonical models by author.

#API
You can access provider data, provider-agnostic model metadata, or the combined catalog through JSON endpoints. Specialized model types are omitted by default; the site includes all model types.

curl https://models.dev/api.json?type=all
curl https://models.dev/models.json?type=all
curl https://models.dev/catalog.json?type=all

#Logos
Provider logos are available at /logos/{provider}.svg where {provider} is the provider ID. Lab logos are available at /logos/labs/{lab}.svg.

curl https://models.dev/logos/anthropic.svg

#SDK
Use the SDK to query the API from your app. It's type-safe and exports the latest snapshot for offline use.

npm install @opencode-ai/models

#Contribute
The data is stored in GitHub as TOML files organized by provider and canonical model.