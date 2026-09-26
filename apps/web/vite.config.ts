import { defineConfig } from 'vite'; import react from '@vitejs/plugin-react';
export default defineConfig({
	plugins:[react()],
	server:{proxy:{
		'/api':{target:'http://api:8000',changeOrigin:true},
		'/auth':{
			target:'http://keycloak:8080',
			changeOrigin:false,
			rewrite:(path)=>path.replace(/^\/auth/,'')
		},
		'/realms':{target:'http://keycloak:8080',changeOrigin:false},
		'/resources':{target:'http://keycloak:8080',changeOrigin:false}
	}}
});
