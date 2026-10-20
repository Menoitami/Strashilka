Shader "SpookyNeuro/VertexLit"
{
    Properties { _Color ("Tint", Color) = (1,1,1,1) }
    SubShader
    {
        Tags { "RenderType"="Opaque" }
        Cull Off
        Pass
        {
            Tags { "LightMode"="ForwardBase" }
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_fwdbase
            #include "UnityCG.cginc"
            #include "Lighting.cginc"
            #include "AutoLight.cginc"
            struct appdata { float4 vertex:POSITION; float3 normal:NORMAL; float4 color:COLOR; };
            struct v2f { float4 pos:SV_POSITION; float3 normal:TEXCOORD0; float3 world:TEXCOORD1; float4 color:COLOR; SHADOW_COORDS(2) };
            fixed4 _Color;
            v2f vert(appdata v)
            {
                v2f o; o.pos=UnityObjectToClipPos(v.vertex);
                o.world=mul(unity_ObjectToWorld,v.vertex).xyz;
                o.normal=UnityObjectToWorldNormal(v.normal);
                o.color=v.color*_Color;
                TRANSFER_SHADOW(o);
                return o;
            }
            fixed4 frag(v2f i):SV_Target
            {
                float3 normal=normalize(i.normal);
                float diffuse=saturate(dot(normal,normalize(UnityWorldSpaceLightDir(i.world))));
                float3 ambient=max(ShadeSH9(float4(normal,1)),.14);
                return fixed4(i.color.rgb*(ambient+_LightColor0.rgb*diffuse*SHADOW_ATTENUATION(i)),1);
            }
            ENDCG
        }
        UsePass "Legacy Shaders/VertexLit/SHADOWCASTER"
    }
    Fallback "Diffuse"
}
