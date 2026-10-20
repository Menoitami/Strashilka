using UnityEngine;

namespace SpookyNeuro
{
    public sealed class OrbitCamera : MonoBehaviour
    {
        public NeuralCreature creature;
        public float distance=5.4f;
        float yaw=20, pitch=8;
        void LateUpdate()
        {
            Vector3 center=Vector3.up*1.5f;
            transform.position=center+Quaternion.Euler(pitch,yaw,0)*new Vector3(0,0,-distance);
            transform.LookAt(center);
        }
        void OnGUI()
        {
            // IMGUI events work without installing/configuring either Unity input package.
            Event current=Event.current;
            if(current.type==EventType.MouseDrag && current.button==1)
            {
                yaw+=current.delta.x*.4f;
                pitch=Mathf.Clamp(pitch+current.delta.y*.4f,-20,65);
                current.Use();
            }
            if(current.type==EventType.ScrollWheel)
            {
                distance=Mathf.Clamp(distance+current.delta.y*.1f,2.2f,12);
                current.Use();
            }
            if(current.type==EventType.KeyDown && creature!=null)
            {
                if(current.keyCode==KeyCode.Space) { creature.walking=!creature.walking; current.Use(); }
                else if(current.keyCode==KeyCode.M) { creature.mutate=!creature.mutate; current.Use(); }
            }
            GUI.Box(new Rect(20,20,380,110),"SpookyNeuro / Neural 3D");
            GUI.Label(new Rect(35,48,350,70),"RMB: orbit | Wheel: zoom\nSpace: walk / rest | M: neural shape shift\nSkinned mesh: 19 bones, true depth and shadows");
        }
    }
}
