using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace SpookyNeuro.Editor
{
    public static class CreateDemo
    {
        [MenuItem("SpookyNeuro/Create 3D Demo")]
        public static void Create()
        {
            // A new additive scene preserves unsaved work in the user's existing scene.
            Scene scene=EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Additive);
            SceneManager.SetActiveScene(scene);
            string[] candidates=AssetDatabase.FindAssets("creature.spooky t:TextAsset");
            if(candidates.Length==0) { Debug.LogError("Copy creature.spooky.json into Assets first."); return; }
            Shader shader=Shader.Find("SpookyNeuro/VertexLit");
            if(shader==null) { Debug.LogError("SpookyNeuro shader not found. Use a Built-in Render Pipeline project."); return; }
            Directory.CreateDirectory("Assets/SpookyNeuro/Generated");
            var mat=new Material(shader);
            string matPath=AssetDatabase.GenerateUniqueAssetPath("Assets/SpookyNeuro/Generated/NeuralSkin.mat");
            AssetDatabase.CreateAsset(mat,matPath);
            var creature=new GameObject("Neural 3D Creature").AddComponent<NeuralCreature>();
            creature.source=AssetDatabase.LoadAssetAtPath<TextAsset>(AssetDatabase.GUIDToAssetPath(candidates[0]));
            creature.material=mat;
            // Construction happens in Play mode, keeping meshes owned by one runtime instance.
            var camera=new GameObject("Orbit Camera").AddComponent<Camera>();
            camera.gameObject.tag="MainCamera";
            camera.fieldOfView=48; camera.clearFlags=CameraClearFlags.SolidColor;
            camera.backgroundColor=new Color(.04f,.06f,.08f);
            camera.transform.position=new Vector3(0,1.8f,-5.4f);
            camera.transform.LookAt(new Vector3(0,1.5f,0));
            camera.gameObject.AddComponent<OrbitCamera>().creature=creature;
            camera.gameObject.AddComponent<AudioListener>();
            var light=new GameObject("Key light").AddComponent<Light>();
            light.type=LightType.Directional; light.intensity=1.25f; light.shadows=LightShadows.Soft;
            light.transform.rotation=Quaternion.Euler(35,-25,0);
            var rim=new GameObject("Rim light").AddComponent<Light>();
            rim.type=LightType.Directional; rim.intensity=.6f; rim.color=new Color(.5f,.8f,1);
            rim.transform.rotation=Quaternion.Euler(25,145,0);
            var ground=GameObject.CreatePrimitive(PrimitiveType.Plane);
            ground.name="Floor"; ground.transform.localScale=Vector3.one*2;
            EditorSceneManager.MarkSceneDirty(scene);
            Selection.activeGameObject=creature.gameObject;
            Debug.Log("3D demo created. Save the new scene, then press Play.");
        }
    }
}
